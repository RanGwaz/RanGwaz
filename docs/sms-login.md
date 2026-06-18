# 手机号登录与短信服务配置

当前项目已经接入手机号验证码登录的前后端接口：

```text
POST /auth/sms-code
POST /auth/phone-login
```

默认配置是本地 mock 模式，后端会把验证码返回给前端并打印到控制台，方便开发调试，不会真的发短信。

## 本地开发

`backend/src/main/resources/application.yml` 默认：

```yaml
app:
  sms:
    mock: true
    dev-code: ""
    code-ttl-seconds: 300
    cooldown-seconds: 60
```

如果想固定验证码，设置：

```yaml
app:
  sms:
    mock: true
    dev-code: "123456"
```

## 阿里云短信准备

阿里云短信服务正式发送前需要：

1. 注册阿里云账号并完成企业实名认证。
2. 开通短信服务。
3. 创建 RAM 用户并创建 AccessKey。
4. 申请短信签名 `SignName`。
5. 申请验证码短信模板 `TemplateCode`，模板变量建议使用 `${code}`。

官方文档：

- https://help.aliyun.com/zh/sms/getting-started/get-started-with-sms
- https://help.aliyun.com/zh/sms/getting-started/use-sms-api
- https://api.aliyun.com/document/Dysmsapi/2017-05-25/SendSms

## 推荐环境变量

不要把密钥写进代码，建议用环境变量：

```powershell
$env:ALIYUN_SMS_ACCESS_KEY_ID="你的 AccessKey ID"
$env:ALIYUN_SMS_ACCESS_KEY_SECRET="你的 AccessKey Secret"
$env:ALIYUN_SMS_SIGN_NAME="你的短信签名"
$env:ALIYUN_SMS_TEMPLATE_CODE="SMS_你的模板CODE"
```

对应配置已经预留在 `application.yml`：

```yaml
app:
  sms:
    mock: true
    provider: aliyun
    aliyun:
      access-key-id: ${ALIYUN_SMS_ACCESS_KEY_ID:}
      access-key-secret: ${ALIYUN_SMS_ACCESS_KEY_SECRET:}
      sign-name: ${ALIYUN_SMS_SIGN_NAME:}
      template-code: ${ALIYUN_SMS_TEMPLATE_CODE:}
```

正式发送前再把 `mock` 改成 `false`，并接入具体短信 SDK 或 HTTP 发送适配器。
