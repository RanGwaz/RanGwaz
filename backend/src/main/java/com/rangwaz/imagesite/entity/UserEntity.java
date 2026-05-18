package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Database entity for an application user.
 */
@Data
public class UserEntity {
    private Long id;
    private String username;
    private String passwordHash;
    private String nickname;
    private String avatarUrl;
    private String backgroundUrl;
    private String bio;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
