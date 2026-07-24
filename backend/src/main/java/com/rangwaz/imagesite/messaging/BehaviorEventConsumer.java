package com.rangwaz.imagesite.messaging;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.entity.UserBehaviorEntity;
import com.rangwaz.imagesite.mapper.BehaviorMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.StringUtils;

/**
 * Persists Kafka behavior events into MySQL analytics tables.
 */
@Component
public class BehaviorEventConsumer {
    private static final Logger log = LoggerFactory.getLogger(BehaviorEventConsumer.class);

    private final BehaviorMapper behaviorMapper;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate transactionTemplate;

    /**
     * Creates the behavior event consumer.
     *
     * @param behaviorMapper behavior mapper
     * @param objectMapper JSON mapper
     * @param transactionManager transaction manager
     */
    public BehaviorEventConsumer(BehaviorMapper behaviorMapper,
                                 ObjectMapper objectMapper,
                                 PlatformTransactionManager transactionManager) {
        this.behaviorMapper = behaviorMapper;
        this.objectMapper = objectMapper;
        this.transactionTemplate = new TransactionTemplate(transactionManager);
    }

    /**
     * Consumes one behavior event from Kafka.
     *
     * @param payload event JSON
     */
    @KafkaListener(topics = "${app.behavior.kafka-topic:vibelo.user-behaviors}")
    public void consume(String payload) {
        BehaviorEvent event;
        try {
            event = objectMapper.readValue(payload, BehaviorEvent.class);
        } catch (JsonProcessingException ex) {
            log.warn("Dropped invalid behavior event payload={}", payload, ex);
            return;
        }
        if (event.imageId() == null || event.imageId() <= 0) return;
        transactionTemplate.executeWithoutResult(status -> persist(event));
    }

    private void persist(BehaviorEvent event) {
        String type = StringUtils.hasText(event.behaviorType()) ? event.behaviorType().trim() : "unknown";
        String scene = StringUtils.hasText(event.scene()) ? event.scene().trim() : "unknown";
        UserBehaviorEntity behavior = new UserBehaviorEntity();
        behavior.setUserId(event.userId());
        behavior.setVisitorId(event.visitorId());
        behavior.setImageId(event.imageId());
        behavior.setBehaviorType(type);
        behavior.setScene(scene);
        behavior.setPositionNo(event.position());
        behavior.setDurationMs(event.duration());
        behavior.setDecisionId(event.decisionId());
        behavior.setEventId(event.eventId());
        behavior.setSource(event.source());
        behavior.setScore(event.score());
        behavior.setOccurredAt(event.occurredAt());
        try {
            behaviorMapper.insert(behavior);
            if ("impression".equalsIgnoreCase(type)) {
                behaviorMapper.insertFeedImpression(
                        event.userId(),
                        event.visitorId(),
                        event.imageId(),
                        scene,
                        event.position(),
                        StringUtils.hasText(event.source()) ? event.source().trim() : scene,
                        event.score(),
                        event.decisionId(),
                        event.eventId(),
                        event.occurredAt()
                );
            }
        } catch (DataIntegrityViolationException ex) {
            log.warn("Dropped behavior event with invalid relation imageId={} userId={}", event.imageId(), event.userId());
        }
    }
}
