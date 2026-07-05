package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Pending or completed profile update review request.
 */
@Data
public class ProfileReviewEntity {
    private Long id;
    private Long userId;
    private String nickname;
    private String avatarUrl;
    private String backgroundUrl;
    private String bio;
    private String status;
    private String reviewReason;
    private LocalDateTime reviewedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
