"""로그인·계정 폼 — 팀공유 전용."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo


class LoginForm(FlaskForm):
    email = StringField("이메일", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("비밀번호", validators=[DataRequired(), Length(min=8, max=128)])
    remember = BooleanField("로그인 유지")
    submit = SubmitField("로그인")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("현재 비밀번호", validators=[DataRequired()])
    new_password = PasswordField(
        "새 비밀번호",
        validators=[DataRequired(), Length(min=8, max=128, message="8자 이상 128자 이하")],
    )
    confirm = PasswordField(
        "새 비밀번호 확인",
        validators=[DataRequired(), EqualTo("new_password", message="비밀번호 불일치")],
    )
    submit = SubmitField("변경")


class InviteUserForm(FlaskForm):
    """admin 전용 — 팀원 초대."""
    email = StringField("이메일", validators=[DataRequired(), Email(), Length(max=255)])
    name = StringField("이름", validators=[DataRequired(), Length(min=1, max=100)])
    role = StringField("역할 (admin/member)", validators=[DataRequired()], default="member")
    temp_password = PasswordField("임시 비밀번호", validators=[DataRequired(), Length(min=8, max=128)])
    submit = SubmitField("초대")
