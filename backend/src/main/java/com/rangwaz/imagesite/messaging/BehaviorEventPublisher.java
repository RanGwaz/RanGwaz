package com.rangwaz.imagesite.messaging;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;

/**
 * Publishes behavior events to Kafka without blocking request handling on MySQL writes.
 */
@Component
public class BehaviorEventPublisher {
    private static final Logger log = LoggerFactory.getLogger(BehaviorEventPublisher.class);

    private final KafkaTemplate<String, String> kafkaTemplate;
    private final ObjectMapper objectMapper;
    private final String topic;

    /**
     * Creates the behavior event publisher.
     *
     * @param kafkaTemplate Kafka template
     * @param objectMapper JSON mapper
     * @param topic behavior topic
     */
    public BehaviorEventPublisher(KafkaTemplate<String, String> kafkaTemplate,
                                  ObjectMapper objectMapper,
                                  @Value("${app.behavior.kafka-topic:vibelo.user-behaviors}") String topic) {
        this.kafkaTemplate = kafkaTemplate;
        this.objectMapper = objectMapper;
        this.topic = topic;
    }

    /**
     * Publishes one behavior event.
     *
     * @param userId optional user id
     * @param imageId image id
     * @param behaviorType behavior type
     * @param scene source scene
     * @param position position in feed
     * @param duration duration in milliseconds
     */
    public void publish(Long userId, Long imageId, String behaviorType, String scene, Integer position, Integer duration) {
        if (imageId == null) return;
        BehaviorEvent event = new BehaviorEvent(
                userId,
                imageId,
                StringUtils.hasText(behaviorType) ? behaviorType.trim() : "unknown",
                StringUtils.hasText(scene) ? scene.trim() : "unknown",
                position,
                duration,
                LocalDateTime.now()
        );
        try {
            String payload = objectMapper.writeValueAsString(event);
            kafkaTemplate.send(topic, String.valueOf(imageId), payload)
                    .whenComplete((result, error) -> {
                        if (error != null) {
                            log.warn("Failed to publish behavior event imageId={} type={}", imageId, behaviorType, error);
                        }
                    });
        } catch (JsonProcessingException ex) {
            log.warn("Failed to serialize behavior event imageId={} type={}", imageId, behaviorType, ex);
        }
    }
}
