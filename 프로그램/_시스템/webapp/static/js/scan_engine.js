/* 모바일 바코드 스캔 공용 엔진 — scan.html · scan_batch.html 이 함께 쓴다.
 *
 * 왜 이 파일인가 (2026-08-05):
 *   기존에는 Android(BarcodeDetector 있음)만 ZBar·전처리·회전 사다리를 탔고,
 *   아이폰은 ZXing 단독의 가장 약한 경로로 떨어졌다 — 사장님 주 기기가 아이폰인데.
 *   여기서는 기기와 무관하게 같은 사다리를 태운다:
 *     Native(있으면) → ZBar(WASM) → ZXing(TRY_HARDER) → 전처리(평활화/샤픈/회전)
 *
 * 성능 설계:
 *   - 4K 프레임을 매번 통째로 디코딩하면 아이폰에서 초당 1~2회로 떨어진다.
 *     매 프레임은 「중앙 밴드 ROI + 최대 1280px 다운스케일」로 빠르게 돌리고,
 *     N프레임마다 전체 프레임·전처리·회전을 섞는다.
 *   - EAN-13 은 체크섬 재검증으로 오독(다른 상품으로 입고되는 사고)을 차단.
 *
 * 의존 (로컬 번들 — CDN 불필요):
 *   /static/vendor/zxing-browser-0.1.5.min.js   → window.ZXingBrowser
 *   /static/vendor/zxing-library-0.21.0.min.js  → window.ZXing
 *   /static/vendor/zbar-wasm-inlined-0.10.1.js  → window.zbarWasm (wasm 인라인)
 */
(function () {
  'use strict';

  const SCAN_FORMATS_NATIVE = ['ean_13', 'ean_8', 'code_128', 'code_39',
                               'upc_a', 'upc_e', 'qr_code', 'data_matrix',
                               'itf', 'codabar'];

  // ───────── 유틸: EAN-13 체크섬 (13자리 숫자만 검사, 그 외 형식은 통과) ─────────
  function validCode(text) {
    const t = (text || '').trim();
    if (t.length < 4) return null;               // 너무 짧은 오탐 차단
    if (/^\d{13}$/.test(t)) {
      let sum = 0;
      for (let i = 0; i < 12; i++) sum += (+t[i]) * (i % 2 === 0 ? 1 : 3);
      if ((10 - (sum % 10)) % 10 !== +t[12]) return null;   // 체크섬 불일치 = 오독
    }
    return t;
  }

  // ───────── 전처리: 히스토그램 평활화 (저조도·물빠진 인쇄) ─────────
  function histEq(img) {
    const d = img.data, n = d.length / 4;
    const hist = new Uint32Array(256);
    for (let i = 0; i < d.length; i += 4) {
      hist[(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) | 0]++;
    }
    const cdf = new Uint32Array(256);
    cdf[0] = hist[0];
    for (let i = 1; i < 256; i++) cdf[i] = cdf[i - 1] + hist[i];
    let cdfMin = 0;
    for (let i = 0; i < 256; i++) { if (cdf[i] > 0) { cdfMin = cdf[i]; break; } }
    const lut = new Uint8Array(256);
    const denom = Math.max(1, n - cdfMin);
    for (let i = 0; i < 256; i++) lut[i] = Math.round(((cdf[i] - cdfMin) / denom) * 255);
    const out = new Uint8ClampedArray(d.length);
    for (let i = 0; i < d.length; i += 4) {
      const v = lut[(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) | 0];
      out[i] = out[i + 1] = out[i + 2] = v; out[i + 3] = 255;
    }
    return new ImageData(out, img.width, img.height);
  }

  // ───────── 전처리: 3x3 샤픈 (흐릿한 초점) ─────────
  function sharpen(img) {
    const w = img.width, h = img.height, src = img.data;
    const out = new Uint8ClampedArray(src);
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = (y * w + x) * 4;
        const v = 5 * src[i]
          - src[i - 4] - src[i + 4]
          - src[i - w * 4] - src[i + w * 4];
        out[i] = out[i + 1] = out[i + 2] = v < 0 ? 0 : (v > 255 ? 255 : v);
        out[i + 3] = 255;
      }
    }
    return new ImageData(out, w, h);
  }

  // ───────── 회전 (세로로 든 바코드) ─────────
  function rotate90(img) {
    const w = img.width, h = img.height;
    const out = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const si = (y * w + x) * 4;
        const di = (x * h + (h - 1 - y)) * 4;
        out[di] = img.data[si]; out[di + 1] = img.data[si + 1];
        out[di + 2] = img.data[si + 2]; out[di + 3] = img.data[si + 3];
      }
    }
    return new ImageData(out, h, w);
  }

  // ───────── 엔진 본체 ─────────
  class Engine {
    constructor(opts) {
      this.video = opts.video;
      this.onCode = opts.onCode;                 // (text) => void
      this.onStats = opts.onStats || function () {};
      this.interval = opts.interval || 55;       // ms — 초당 ~18 시도
      this.hitCooldown = opts.hitCooldown || 300;// ms — 인식 직후 쉬는 시간(연속 스캔)
      this.isActive = opts.isActive || (() => true);  // false 면 그 프레임 건너뜀
      this.tries = 0;
      this._stopped = false;
      this._detector = null;
      this._zxing = null;
      this._canvas = document.createElement('canvas');
      this._ctx = this._canvas.getContext('2d', { willReadFrequently: true });
      this._work = document.createElement('canvas');
      this._wctx = this._work.getContext('2d', { willReadFrequently: true });
    }

    async init() {
      const parts = [];
      // 1) Native BarcodeDetector (Android Chrome/Edge — 최고속)
      if ('BarcodeDetector' in window) {
        try {
          const supported = await BarcodeDetector.getSupportedFormats();
          const formats = supported.filter(f => SCAN_FORMATS_NATIVE.includes(f));
          this._detector = new BarcodeDetector({ formats: formats.length ? formats : undefined });
          parts.push('Native');
        } catch (e) { console.warn('[scan-engine] Native init 실패', e); }
      }
      // 2) ZBar WASM (전 기기 — 1D 최강)
      if (window.zbarWasm && window.zbarWasm.scanImageData) parts.push('ZBar');
      // 3) ZXing (전 기기 — 폴백 + 회전·저품질 보강)
      try {
        const Z = window.ZXing;
        const ZB = window.ZXingBrowser;
        if (Z && ZB) {
          const hints = new Map();
          hints.set(Z.DecodeHintType.TRY_HARDER, true);
          if (Z.DecodeHintType.ALSO_INVERTED) hints.set(Z.DecodeHintType.ALSO_INVERTED, true);
          hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [
            Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8,
            Z.BarcodeFormat.CODE_128, Z.BarcodeFormat.CODE_39,
            Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E,
            Z.BarcodeFormat.QR_CODE, Z.BarcodeFormat.DATA_MATRIX,
            Z.BarcodeFormat.ITF, Z.BarcodeFormat.CODABAR,
          ]);
          this._zxing = new ZB.BrowserMultiFormatReader(hints);
          parts.push('ZXing');
        }
      } catch (e) { console.warn('[scan-engine] ZXing init 실패', e); }

      if (!parts.length) throw new Error('바코드 디코더를 하나도 준비하지 못함');
      this.engineLabel = parts.join('+');
      this.onStats({ engine: this.engineLabel, tries: 0 });
      return this;
    }

    // ImageData 한 장에 3중 디코더 시도
    async _decodeImage(img) {
      // ZBar — 1D 인식률이 가장 좋아 첫 순서
      if (window.zbarWasm && window.zbarWasm.scanImageData) {
        try {
          const rs = await window.zbarWasm.scanImageData(img);
          if (rs && rs.length) {
            const v = validCode(rs[0].decode ? rs[0].decode() : (rs[0].data || ''));
            if (v) return v;
          }
        } catch (e) { /* 다음 디코더로 */ }
      }
      // Native — canvas 필요
      if (this._detector) {
        try {
          this._work.width = img.width; this._work.height = img.height;
          this._wctx.putImageData(img, 0, 0);
          const codes = await this._detector.detect(this._work);
          if (codes.length) {
            const v = validCode(codes[0].rawValue);
            if (v) return v;
          }
        } catch (e) { /* 다음 */ }
      }
      // ZXing — canvas 디코드
      if (this._zxing) {
        try {
          this._work.width = img.width; this._work.height = img.height;
          this._wctx.putImageData(img, 0, 0);
          const r = this._zxing.decodeFromCanvas(this._work);
          if (r) {
            const v = validCode(r.getText());
            if (v) return v;
          }
        } catch (e) { /* NotFound — 정상 */ }
      }
      return null;
    }

    // 비디오 프레임에서 (ROI·스케일 적용한) ImageData 추출
    _grab(scaleMax, roiBand) {
      const vw = this.video.videoWidth, vh = this.video.videoHeight;
      if (!vw || !vh) return null;
      let sx = 0, sy = 0, sw = vw, sh = vh;
      if (roiBand) {           // 중앙 밴드 — 가로 전체 × 세로 60%
        sh = Math.round(vh * 0.6);
        sy = Math.round((vh - sh) / 2);
      }
      let dw = sw, dh = sh;
      if (scaleMax && Math.max(sw, sh) > scaleMax) {
        const k = scaleMax / Math.max(sw, sh);
        dw = Math.round(sw * k); dh = Math.round(sh * k);
      }
      this._canvas.width = dw; this._canvas.height = dh;
      this._ctx.drawImage(this.video, sx, sy, sw, sh, 0, 0, dw, dh);
      return this._ctx.getImageData(0, 0, dw, dh);
    }

    // 한 프레임치 사다리 — 찾으면 코드 문자열, 못 찾으면 null
    async _scanFrame(frame) {
      // A. 매 프레임 — 중앙 밴드 ROI, ≤1280px (빠른 경로)
      const roi = this._grab(1280, true);
      if (roi) {
        const r1 = await this._decodeImage(roi);
        if (r1) return r1;
      }
      // B. 매 2프레임 — 전체 프레임 ≤1600px (프레임 밖 바코드·QR)
      if (frame % 2 === 1) {
        const full = this._grab(1600, false);
        if (full) {
          const r2 = await this._decodeImage(full);
          if (r2) return r2;
        }
      }
      // C. 매 3프레임 — 평활화 (저조도·인쇄 바램)
      if (frame % 3 === 2 && roi) {
        const eq = histEq(roi);
        const r3 = await this._decodeImage(eq);
        if (r3) return r3;
        // C-2. 매 6프레임 — 샤픈 (흐릿한 초점)
        if (frame % 6 === 5) {
          const r4 = await this._decodeImage(sharpen(eq));
          if (r4) return r4;
        }
        // C-3. 매 6프레임(어긋난 위상) — 90도 회전 (세로로 든 바코드)
        if (frame % 6 === 2) {
          const r5 = await this._decodeImage(rotate90(eq));
          if (r5) return r5;
        }
      }
      return null;
    }

    async loop() {
      let frame = 0;
      while (!this._stopped) {
        let hit = false;
        if (this.video.readyState >= 2 && this.video.videoWidth && this.isActive()) {
          this.tries++;
          // onStats 는 화면 DOM 을 만진다 — 여기서 터지면 루프가 통째로 죽으므로 격리
          try { this.onStats({ engine: this.engineLabel, tries: this.tries }); } catch (e) {}
          try {
            const code = await this._scanFrame(frame);
            if (code) {
              if (await this._emit(code)) return;   // 단건 스캔 — 루프 종료
              hit = true;
            }
          } catch (e) { /* 프레임 단위 오류는 무시하고 계속 */ }
          frame++;
        }
        // ★ 이 sleep 은 「루프의 유일한 매크로태스크 양보점」이다.
        //   예전엔 인식 성공 시 continue 로 여길 건너뛰었는데, 연속 스캔(일괄 입·출고)은
        //   같은 바코드를 매 프레임 다시 인식하므로 양보가 영원히 오지 않았다
        //   → 화면·타이머·fetch 가 전부 굶어 「스캔이 아예 안 되는」 먹통이 됐다.
        //   (2026-08-06 라이브 실측: 일괄 페이지 메인스레드 5초+ 무응답, lookup 요청 0건)
        //   단독 스캔은 frozen 게이트 덕에 우연히 빠져나가고 있었을 뿐이다.
        //   인식 직후엔 조금 더 쉰다 — 같은 코드를 초당 18번 다시 읽어봐야 낭비.
        await new Promise(r => setTimeout(r, hit ? this.hitCooldown : this.interval));
      }
    }

    // onCode 가 true 를 돌려주면 루프 종료(단건 스캔), false/undefined 면 계속(연속 스캔)
    async _emit(text) {
      try {
        const stop = await this.onCode(text);
        if (stop === true) { this._stopped = true; return true; }
      } catch (e) { console.error('[scan-engine] onCode 오류', e); }
      return false;
    }

    stop() { this._stopped = true; }
  }

  // 공개 API
  window.ScanEngine = {
    /** opts: {video, onCode(text)→bool|Promise, onStats({engine,tries}), interval?, hitCooldown?, isActive?()} */
    async start(opts) {
      const eng = new Engine(opts);
      await eng.init();
      eng.loop();   // fire-and-forget — stop() 으로 종료
      return eng;
    },
  };
})();
