package com.rangwaz.imagesite.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

class AliyunSmsSenderTest {
    @Test
    void sendsViaNumberAuthSmsVerifyCodeApi() throws Exception {
        ArrayBlockingQueue<String> requests = new ArrayBlockingQueue<>(1);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requests.offer(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = """
                    {"Code":"OK","Success":true,"RequestId":"test-request","Model":{"BizId":"test-biz"}}
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json;charset=UTF-8");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();

        try {
            AliyunSmsSender sender = new AliyunSmsSender(new ObjectMapper());
            ReflectionTestUtils.setField(sender, "endpoint", "http://127.0.0.1:" + server.getAddress().getPort() + "/");
            ReflectionTestUtils.setField(sender, "regionId", "cn-hangzhou");
            ReflectionTestUtils.setField(sender, "accessKeyId", "test-key");
            ReflectionTestUtils.setField(sender, "accessKeySecret", "test-secret");
            ReflectionTestUtils.setField(sender, "signName", "速通互联验证码");
            ReflectionTestUtils.setField(sender, "templateCode", "100001");
            ReflectionTestUtils.setField(sender, "countryCode", "86");
            ReflectionTestUtils.setField(sender, "intervalSeconds", 60L);
            ReflectionTestUtils.setField(sender, "duplicatePolicy", 1);
            ReflectionTestUtils.setField(sender, "returnVerifyCode", false);
            ReflectionTestUtils.setField(sender, "autoRetry", 1);

            sender.sendVerificationCode("19812345938", "123456", Duration.ofSeconds(300), "login");

            Map<String, String> params = parseForm(requests.poll(2, TimeUnit.SECONDS));
            assertThat(params)
                    .containsEntry("Action", "SendSmsVerifyCode")
                    .containsEntry("Version", "2017-05-25")
                    .containsEntry("PhoneNumber", "19812345938")
                    .containsEntry("CountryCode", "86")
                    .containsEntry("SignName", "速通互联验证码")
                    .containsEntry("TemplateCode", "100001")
                    .containsEntry("ValidTime", "300")
                    .containsEntry("Interval", "60")
                    .containsEntry("DuplicatePolicy", "1")
                    .containsEntry("ReturnVerifyCode", "false")
                    .containsEntry("AutoRetry", "1")
                    .containsEntry("OutId", "login");
            assertThat(params).doesNotContainKey("PhoneNumbers");
            assertThat(params.get("TemplateParam")).contains("\"code\":\"123456\"", "\"min\":\"5\"");
        } finally {
            server.stop(0);
        }
    }

    private static Map<String, String> parseForm(String body) {
        assertThat(body).isNotBlank();
        return Arrays.stream(body.split("&"))
                .map(part -> part.split("=", 2))
                .collect(Collectors.toMap(
                        part -> decode(part[0]),
                        part -> part.length > 1 ? decode(part[1]) : ""
                ));
    }

    private static String decode(String value) {
        return URLDecoder.decode(value, StandardCharsets.UTF_8);
    }
}
