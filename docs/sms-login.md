# 手机号登录与号码认证短信配置

当前项目支持两种手机号登录方式：

```text
POST /auth/phone-password-login
POST /auth/sms-code
POST /auth/phone-login
```

推荐用户日常使用“手机号 + 密码”登录。验证码登录主要用于首次注册，或用户选择短信验证码登录的场景。

## 登录体验

1. 密码登录：输入手机号和密码，不发送短信。
2. 验证码登录：已注册手机号输入短信验证码即可登录，不强制修改密码。
3. 新手机号注册：先获取验证码，验证码正确后必须设置 6-64 位密码，并再次输入确认密码。
4. 新手机号只有在验证码正确、两次密码一致时才会注册成功。
5. 数据库层通过 `uk_app_users_phone` 唯一索引保证一个手机号只能注册一个账号。

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

推荐使用环境变量，不要把密钥写进代码或文档：

```powershell
$env:ALIYUN_PNVS_SMS_ACCESS_KEY_ID="你的 AccessKey ID"
$env:ALIYUN_PNVS_SMS_ACCESS_KEY_SECRET="你的 AccessKey Secret"
$env:ALIYUN_PNVS_SMS_SIGN_NAME="速通互联验证码"
$env:ALIYUN_PNVS_SMS_TEMPLATE_CODE="100001"
```
