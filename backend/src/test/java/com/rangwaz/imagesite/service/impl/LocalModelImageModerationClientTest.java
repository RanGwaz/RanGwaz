package com.rangwaz.imagesite.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.config.ContentSafetyProperties;
import com.rangwaz.imagesite.service.ImageModerationClient;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

class LocalModelImageModerationClientTest {
    @Test
    void sendsImageBytesToLocalModelService() throws Exception {
        ArrayBlockingQueue<String> requests = new ArrayBlockingQueue<>(1);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/moderate/image", exchange -> {
            requests.offer(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = """
                    {"allowed":true,"reason":"pass","requestId":"local-test"}
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json;charset=UTF-8");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();

        try {
            LocalModelImageModerationClient client = new LocalModelImageModerationClient(new ObjectMapper(), properties(server));

            ImageModerationClient.ModerationDecision decision = client.check(null, new byte[]{1, 2, 3}, "image/jpeg");

            assertThat(decision.allowed()).isTrue();
            assertThat(decision.requestId()).isEqualTo("local-test");
            assertThat(requests.poll(2, TimeUnit.SECONDS)).contains("\"imageBase64\":\"AQID\"", "\"contentType\":\"image/jpeg\"");
        } finally {
            server.stop(0);
        }
    }

    private ContentSafetyProperties properties(HttpServer server) {
        ContentSafetyProperties properties = new ContentSafetyProperties();
        properties.getCloud().setEnabled(true);
        properties.getCloud().setProvider("local-model");
        properties.getCloud().getModel().setUrl("http://127.0.0.1:" + server.getAddress().getPort() + "/moderate/image");
        return properties;
    }
}
