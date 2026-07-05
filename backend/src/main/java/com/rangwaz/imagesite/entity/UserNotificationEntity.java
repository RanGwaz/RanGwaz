package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * In-app user notification row.
 */
@Data
public class UserNotificationEntity {
    private Long id;
    private Long userId;
    private String type;
    private String title;
    private String content;
    private String targetType;
    private Long targetId;
    private Boolean read;
    private LocalDateTime createdAt;
}
