# 手机号登录与号码认证短信配置

当前项目支持两种手机号登录方式：

```text
POST /auth/phone-password-login
POST /auth/sms-code
POST /auth/phone-login
POST /auth/phone-password-reset
```

登录弹窗默认使用验证码，也保留手机号密码登录。首次注册会建立一个真正可用的密码；忘记密码必须通过独立的短信重置接口完成，验证码登录本身不会再隐式修改密码。

## 登录体验

1. 密码登录：输入手机号和密码，不发送短信。
2. 验证码登录：已注册手机号输入短信验证码即可登录，不强制修改密码。
3. 新手机号注册：先获取验证码，必须设置并确认 8-64 个字符、UTF-8 编码不超过 72 字节的密码。
4. 新手机号只有在验证码正确、两次密码一致时才会注册成功。
5. 忘记密码：使用 `password_reset` 场景获取短信，再调用 `/auth/phone-password-reset`；未注册手机号不会被误创建为账号。
6. 数据库层通过 `uk_app_users_phone` 唯一索引保证一个手机号只能注册一个账号。

新密码使用带独立随机盐的 BCrypt 保存。旧版本固定盐 SHA-256 密码仍可登录；符合 BCrypt 72-byte 输入限制时会在下一次密码登录后透明升级，超限旧密码建议通过短信重置。

## 本地开发

```yaml
app:
  sms:
    mock: true
    dev-code: "123456"
    code-ttl-seconds: 300
    cooldown-seconds: 60
```

## 阿里云号码认证短信

当前真实发送接入的是号码认证服务里的短信认证接口，不是标准短信服务 `Dysmsapi.SendSms`：

```text
Dypnsapi.SendSmsVerifyCode
```

当前项目默认使用签名 `速通互联验证码`、登录/注册模板 Code `100001`。

推荐使用统一环境变量，不要把密钥写进代码或文档；旧的 `ALIYUN_PNVS_SMS_*` 名称仍兼容：

```powershell
$env:ALIYUN_SMS_ACCESS_KEY_ID="你的 AccessKey ID"
$env:ALIYUN_SMS_ACCESS_KEY_SECRET="你的 AccessKey Secret"
$env:ALIYUN_SMS_SIGN_NAME="你的短信签名"
$env:ALIYUN_SMS_TEMPLATE_CODE="100001"
```
