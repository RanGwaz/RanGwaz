package com.rangwaz.imagesite.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.config.SearchProperties;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ElasticsearchSearchClientTest {
    @Test
    void readsVerifiedCertificateFromTheOnlyMappedConcreteIndex() throws IOException {
        String response = """
                {
                  "rangwaz-images-candidate-20260808": {
                    "mappings": {
                      "_meta": {
                        "vibelo_reindex_certificate": {
                          "schema": "v1",
                          "status": "verified",
                          "published_count": 126945,
                          "target_alias": "rangwaz-images",
                          "target_index": "rangwaz-images-candidate-20260808",
                          "source_fingerprint": "ignored-by-java",
                          "created_at_utc": "2026-08-08T11:00:00Z"
                        }
                      }
                    }
                  }
                }
                """;
        HttpServer server = jsonServer("/rangwaz-images/_mapping", response);
        try {
            ElasticsearchSearchClient client = client(server);

            ElasticsearchSearchClient.ReindexCertificate certificate = client
                    .readVerifiedReindexCertificate("rangwaz-images")
                    .orElseThrow();

            assertEquals("rangwaz-images-candidate-20260808", certificate.concreteIndex());
            assertEquals(126945L, certificate.publishedCount());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsCertificateWhenAliasMapsToMultipleConcreteIndices() throws IOException {
        String response = """
                {
                  "candidate-a": {"mappings":{"_meta":{"vibelo_reindex_certificate":{"schema":"v1","status":"verified","published_count":12}}}},
                  "candidate-b": {"mappings":{"_meta":{"vibelo_reindex_certificate":{"schema":"v1","status":"verified","published_count":12}}}}
                }
                """;
        HttpServer server = jsonServer("/rangwaz-images/_mapping", response);
        try {
            assertTrue(client(server).readVerifiedReindexCertificate("rangwaz-images").isEmpty());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsCertificateThatIsNotVerified() throws IOException {
        String response = """
                {
                  "candidate-a": {
                    "mappings": {
                      "_meta": {
                        "vibelo_reindex_certificate": {
                          "schema": "v1",
                          "status": "building",
                          "published_count": 12
                        }
                      }
                    }
                  }
                }
                """;
        HttpServer server = jsonServer("/rangwaz-images/_mapping", response);
        try {
            assertTrue(client(server).readVerifiedReindexCertificate("rangwaz-images").isEmpty());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsCertificateWithNonPositivePublishedCount() throws IOException {
        String response = """
                {
                  "candidate-a": {
                    "mappings": {
                      "_meta": {
                        "vibelo_reindex_certificate": {
                          "schema": "v1",
                          "status": "verified",
                          "published_count": 0
                        }
                      }
                    }
                  }
                }
                """;
        HttpServer server = jsonServer("/rangwaz-images/_mapping", response);
        try {
            assertTrue(client(server).readVerifiedReindexCertificate("rangwaz-images").isEmpty());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsCertificateCopiedFromAnotherAliasOrConcreteIndex() throws IOException {
        String response = """
                {
                  "candidate-a": {
                    "mappings": {
                      "_meta": {
                        "vibelo_reindex_certificate": {
                          "schema": "v1",
                          "status": "verified",
                          "published_count": 12,
                          "target_alias": "another-alias",
                          "target_index": "candidate-b"
                        }
                      }
                    }
                  }
                }
                """;
        HttpServer server = jsonServer("/rangwaz-images/_mapping", response);
        try {
            assertTrue(client(server).readVerifiedReindexCertificate("rangwaz-images").isEmpty());
        } finally {
            server.stop(0);
        }
    }

    private ElasticsearchSearchClient client(HttpServer server) {
        SearchProperties properties = new SearchProperties();
        properties.setElasticsearchUrl("http://127.0.0.1:" + server.getAddress().getPort());
        return new ElasticsearchSearchClient(properties, new ObjectMapper());
    }

    private HttpServer jsonServer(String path, String response) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(path, exchange -> {
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.start();
        return server;
    }
}
