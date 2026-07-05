package com.rangwaz.imagesite.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.config.ContentSafetyProperties;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AliyunImageModerationClientTest {
    @Test
    void sendsImageModerationRequestAndReportsProviderMsg() throws Exception {
        ArrayBlockingQueue<String> requests = new ArrayBlockingQueue<>(1);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requests.offer(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = """
                    {"Code":400,"Msg":"service baselineCheck is not opened","RequestId":"test-request"}
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json;charset=UTF-8");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();

        try {
            AliyunImageModerationClient client = new AliyunImageModerationClient(new ObjectMapper(), properties(server));

            BusinessException exception = assertThrows(BusinessException.class,
                    () -> client.check("https://img.example.com/a.jpg", new byte[]{1, 2, 3}, "image/jpeg"));

            assertThat(exception.getMessage()).contains("service baselineCheck is not opened");
            Map<String, String> params = parseForm(requests.poll(2, TimeUnit.SECONDS));
            assertThat(params)
                    .containsEntry("Action", "ImageModeration")
                    .containsEntry("Version", "2022-03-02")
                    .containsEntry("RegionId", "cn-shanghai")
                    .containsEntry("Service", "baselineCheck");
            assertThat(params.get("ServiceParameters")).contains("\"dataId\"", "\"imageUrl\":\"https://img.example.com/a.jpg\"");
        } finally {
            server.stop(0);
        }
    }

    @Test
    void requiresPublicImageUrl() {
        ContentSafetyProperties properties = new ContentSafetyProperties();
        properties.getCloud().setEnabled(true);
        ContentSafetyProperties.Aliyun aliyun = properties.getCloud().getAliyun();
        aliyun.setAccessKeyId("test-key");
        aliyun.setAccessKeySecret("test-secret");
        AliyunImageModerationClient client = new AliyunImageModerationClient(new ObjectMapper(), properties);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> client.check("/media/object/a.jpg", new byte[]{1, 2, 3}, "image/jpeg"));

        assertThat(exception.getMessage()).contains("公网可访问");
    }

    private ContentSafetyProperties properties(HttpServer server) {
        ContentSafetyProperties properties = new ContentSafetyProperties();
        properties.getCloud().setEnabled(true);
        properties.getCloud().setFailClosed(true);
        ContentSafetyProperties.Aliyun aliyun = properties.getCloud().getAliyun();
        aliyun.setEndpoint("http://127.0.0.1:" + server.getAddress().getPort() + "/");
        aliyun.setRegionId("cn-shanghai");
        aliyun.setAccessKeyId("test-key");
        aliyun.setAccessKeySecret("test-secret");
        aliyun.setService("baselineCheck");
        return properties;
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
