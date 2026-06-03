package com.rangwaz.imagesite.messaging;

import java.time.LocalDateTime;

/**
 * User behavior event transported through Kafka.
 *
 * @param userId optional user id
 * @param imageId image id
 * @param behaviorType behavior type such as impression, click, view, like, favorite, comment
 * @param scene source scene
 * @param position position in the feed
 * @param duration duration in milliseconds
 * @param occurredAt event time at API receive
 */
public record BehaviorEvent(Long userId,
                            Long imageId,
                            String behaviorType,
                            String scene,
                            Integer position,
                            Integer duration,
                            LocalDateTime occurredAt) {
}
