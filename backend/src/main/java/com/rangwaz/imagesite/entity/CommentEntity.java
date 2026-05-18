package com.rangwaz.imagesite.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * Database entity for a visible post comment.
 */
@Data
public class CommentEntity {
    private Long id;
    private Long postId;
    private Long authorId;
    private Long parentCommentId;
    private String content;
    private String status;
    private LocalDateTime createdAt;
}
