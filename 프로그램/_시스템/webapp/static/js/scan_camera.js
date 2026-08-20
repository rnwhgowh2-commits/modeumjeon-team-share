/* 모바일 스캔 공용 카메라 — scan.html · scan_batch.html · scan_ship.html 이 함께 쓴다.
 *
 * 왜 이 파일인가 (2026-08-06):
 *   단독 스캔(scan.html)에만 있던 카메라 사다리(후면 카메라 지정·4K→1080p 폴백·매크로 초점·
 *   줌·플래시·탭 재초점·iOS 자동 재초점)를 일괄 입·출고(scan_batch.html)는 갖고 있지 않았다.
 *   일괄 쪽은 facingMode 만 주고 끝 — 렌즈가 어긋나거나 초점이 안 잡히면 손쓸 방법이 없고,
 *   실패해도 2.5초 토스트 하나가 전부라 「그냥 안 되는 화면」이 됐다.
 *   디코더는 이미 scan_engine.js 로 합쳤으니, 카메라도 여기 한 곳으로 합친다.
 *
 * 쓰는 법:
 *   const cam = await ScanCamera.open({ video, els: {...}, onHint });
 *   cam.stop();
 */
(function () {
  'use strict';

  const HINT_DEFAULT = '바코드를 비춰주세요';

  class Camera {
    constructor(opts) {
      this.video = opts.video;
      this.els = opts.els || {};          // {torch, zoomWrap, zoomRange, zoomVal, camSwitch, res}
      this.onHint = opts.onHint || function () {};
      this.isActive = opts.isActive || (() => true);
      this.stream = null;
      this.track = null;
      this.cameras = [];
      this.camIdx = 0;
      this._refocus = null;
      this._phase = 0;
    }

    // 후면 카메라 우선 정렬 — 권한 전에는 label 이 비어 정렬이 무의미할 수 있다(그때는 facingMode 로 간다)
    async listCameras() {
      try {
        const devs = await navigator.mediaDevices.enumerateDevices();
        this.cameras = devs.filter(d => d.kind === 'videoinput');
        this.cameras.sort((a, b) => {
          const ar = /back|rear|environment|후면/i.test(a.label || '') ? -1 : 1;
          const br = /back|rear|environment|후면/i.test(b.label || '') ? -1 : 1;
          return ar - br;
        });
      } catch (e) {
        this.cameras = [];
      }
      return this.cameras;
    }

    _constraints(camId) {
      // ★ 4K 시도 → 미지원 시 1080p 폴백. 후면 + 연속 초점 + macro(가까운 거리)
      const base = camId
        ? { deviceId: { exact: camId } }
        : { facingMode: { ideal: 'environment' } };
      return [
        { video: Object.assign({}, base, {
            width: { ideal: 3840 }, height: { ideal: 2160 },
            advanced: [{ focusMode: 'continuous' }, { focusDistance: 0.15 }],
          }), audio: false },
        { video: Object.assign({}, base, {
            width: { ideal: 1920 }, height: { ideal: 1080 },
            advanced: [{ focusMode: 'continuous' }],
          }), audio: false },
      ];
    }

    async start(camId) {
      if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
      let lastErr = null;
      // 1차 — 지정된(또는 후면) 카메라. 2차 — deviceId 가 거부되면 facingMode 로 재시도.
      const ladders = camId ? [this._constraints(camId), this._constraints(null)]
                            : [this._constraints(null)];
      for (const ladder of ladders) {
        for (const c of ladder) {
          try { this.stream = await navigator.mediaDevices.getUserMedia(c); break; }
          catch (e) { lastErr = e; }
        }
        if (this.stream) break;
      }
      if (!this.stream) throw lastErr || new Error('카메라 시작 실패');

      this.track = this.stream.getVideoTracks()[0];
      this.video.srcObject = this.stream;
      await this.video.play();
      this._wireCapabilities();
      return this;
    }

    // 플래시 / 줌 / 해상도 — 기기가 지원하는 것만 화면에 노출
    _wireCapabilities() {
      const caps = this.track.getCapabilities ? this.track.getCapabilities() : {};
      const settings = this.track.getSettings ? this.track.getSettings() : {};
      const els = this.els;

      if (els.res) els.res.textContent = `${settings.width || '?'}×${settings.height || '?'}`;
      if (els.torch) els.torch.style.display = caps.torch ? '' : 'none';
      if (els.camSwitch) els.camSwitch.style.display = this.cameras.length > 1 ? '' : 'none';

      if (els.zoomWrap && els.zoomRange) {
        if (caps.zoom) {
          els.zoomWrap.style.display = '';
          const zr = els.zoomRange;
          zr.min = caps.zoom.min; zr.max = caps.zoom.max; zr.step = caps.zoom.step || 0.1;
          zr.value = settings.zoom || caps.zoom.min;
          if (els.zoomVal) els.zoomVal.textContent = parseFloat(zr.value).toFixed(1) + 'x';
          zr.oninput = async () => {
            try { await this.track.applyConstraints({ advanced: [{ zoom: parseFloat(zr.value) }] }); }
            catch (e) { console.warn('zoom fail', e); }
            if (els.zoomVal) els.zoomVal.textContent = parseFloat(zr.value).toFixed(1) + 'x';
          };
        } else {
          els.zoomWrap.style.display = 'none';
        }
      }
    }

    /* iOS Safari 는 focusMode:continuous 를 줘도 장면이 안 변하면 재초점을 안 한다.
       1.5초마다 미세 줌·초점 흔들기로 「장면이 변했다」 신호를 만들어 재초점을 유도. */
    startAutoRefocus() {
      if (this._refocus || !this.track) return;
      this._refocus = setInterval(async () => {
        if (!this.track || !this.isActive()) return;
        try {
          const caps = this.track.getCapabilities ? this.track.getCapabilities() : {};
          if (caps.zoom) {
            const cur = this.track.getSettings().zoom || caps.zoom.min;
            const delta = (caps.zoom.max - caps.zoom.min) * 0.02;
            const nudged = Math.max(caps.zoom.min, Math.min(caps.zoom.max,
              cur + (this._phase % 2 === 0 ? delta : -delta)));
            await this.track.applyConstraints({ advanced: [{ zoom: nudged }] });
            await new Promise(r => setTimeout(r, 50));
            await this.track.applyConstraints({ advanced: [{ zoom: cur }] });
          }
          if (caps.focusMode && caps.focusMode.includes('manual')) {
            const dists = [0.1, 0.15, 0.2, 0.3];
            await this.track.applyConstraints({
              advanced: [{ focusMode: 'manual', focusDistance: dists[this._phase % dists.length] }] });
            await new Promise(r => setTimeout(r, 80));
            await this.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
          } else if (caps.focusMode && caps.focusMode.includes('continuous')) {
            await this.track.applyConstraints({ advanced: [{ focusMode: 'single-shot' }] }).catch(() => {});
            await new Promise(r => setTimeout(r, 80));
            await this.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
          }
          this._phase++;
        } catch (e) { /* iOS 일부 거부 — 무시 */ }
      }, 1500);
    }

    stopAutoRefocus() {
      if (this._refocus) { clearInterval(this._refocus); this._refocus = null; }
    }

    async toggleTorch() {
      if (!this.track) return;
      const caps = this.track.getCapabilities ? this.track.getCapabilities() : {};
      const btn = this.els.torch;
      if (!caps.torch) { if (window.showToast) showToast('플래시 지원 안 됨', 'info'); return; }
      const on = btn ? btn.classList.toggle('on') : true;
      try { await this.track.applyConstraints({ advanced: [{ torch: on }] }); }
      catch (e) { console.warn('torch fail', e); if (btn) btn.classList.remove('on'); }
    }

    // 화면 탭 — 그 자리에서 재초점(매크로 지원 기기는 매크로로)
    async tapFocus() {
      if (!this.track) return;
      const caps = this.track.getCapabilities ? this.track.getCapabilities() : {};
      if (!caps.focusMode || !caps.focusMode.includes('manual')) {
        try { await this.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) {}
        this.onHint('재초점');
        setTimeout(() => this.onHint(HINT_DEFAULT), 700);
        return;
      }
      try {
        await this.track.applyConstraints({ advanced: [{ focusMode: 'manual', focusDistance: 0.15 }] });
        this.onHint('매크로 초점');
        setTimeout(() => this.onHint(HINT_DEFAULT), 1500);
      } catch (e) { console.warn('focus fail', e); }
    }

    async switchCam() {
      if (this.cameras.length < 2) { if (window.showToast) showToast('카메라 1개만 사용 가능', 'info'); return; }
      this.camIdx = (this.camIdx + 1) % this.cameras.length;
      try { await this.start(this.cameras[this.camIdx].deviceId); }
      catch (e) { if (window.showToast) showToast('카메라 전환 실패', 'error'); }
    }

    stop() {
      this.stopAutoRefocus();
      if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
      this.track = null;
    }
  }

  window.ScanCamera = {
    /** opts: {video, els{torch,zoomWrap,zoomRange,zoomVal,camSwitch,res}, onHint, isActive} */
    async open(opts) {
      const cam = new Camera(opts);
      await cam.listCameras();
      // label 이 채워진 후면 카메라가 있으면 그걸 정확히 지정, 아니면 facingMode 에 맡긴다
      const backLabeled = cam.cameras.find(d => d.label && /back|rear|environment|후면/i.test(d.label));
      await cam.start(backLabeled ? backLabeled.deviceId : null);
      // 권한 승인 후엔 label 이 채워진다 — 카메라 전환 버튼 노출을 위해 다시 조회
      if (!cam.cameras.some(d => d.label)) { await cam.listCameras(); cam._wireCapabilities(); }
      cam.startAutoRefocus();
      return cam;
    },

    // 사용자에게 보여줄 말로 바꾼다 — 「무슨 일이 났는지」가 화면에 남아야 한다
    friendlyError(e) {
      const msg = (e && (e.message || e.name)) ? (e.message || e.name) : String(e);
      if (/Permission|NotAllowed/i.test(msg)) return '카메라 권한이 거부됨. 설정에서 허용해주세요.';
      if (/NotFound|카메라 없음|DevicesNotFound/i.test(msg)) return '카메라 없음 — SKU 직접 입력해주세요.';
      if (/NotReadable|TrackStart/i.test(msg)) return '카메라를 다른 앱이 쓰고 있어요. 그 앱을 닫고 새로고침해주세요.';
      return msg;
    },
  };
})();
