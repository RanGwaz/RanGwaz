package com.rangwaz.imagesite.messaging;

import java.time.LocalDateTime;

/**
 * User behavior event transported through Kafka.
 *
 * @param userId optional user id
 * @param visitorId stable anonymous visitor id
 * @param imageId image id
 * @param behaviorType behavior type such as impression, click, view, like, favorite, comment
 * @param scene source scene
 * @param position position in the feed
 * @param duration duration in milliseconds
 * @param latitude optional latitude from browser geolocation
 * @param longitude optional longitude from browser geolocation
 * @param locationLabel optional human-readable location label
 * @param occurredAt event time at API receive
 */
public record BehaviorEvent(Long userId,
                            String visitorId,
                            Long imageId,
                            String behaviorType,
                            String scene,
                            Integer position,
                            Integer duration,
                            Double latitude,
                            Double longitude,
                            String locationLabel,
                            String decisionId,
                            String eventId,
                            String source,
                            Double score,
                            LocalDateTime occurredAt) {
}
