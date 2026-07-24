package com.rangwaz.imagesite.entity;

import lombok.Data;

/**
 * Database entity for image behavior events.
 */
@Data
public class UserBehaviorEntity {
    private Long userId;
    private String visitorId;
    private Long imageId;
    private String behaviorType;
    private String scene;
    private Integer positionNo;
    private Integer durationMs;
    private String decisionId;
    private String eventId;
    private String source;
    private Double score;
    private java.time.LocalDateTime occurredAt;
}
