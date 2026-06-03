package com.rangwaz.imagesite.config;

import org.apache.kafka.clients.admin.NewTopic;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;

/**
 * Kafka topic definitions for behavior event streams.
 */
@Configuration
public class BehaviorKafkaTopicConfig {
    /**
     * Creates the behavior event topic in local development.
     *
     * @param topic topic name
     * @return Kafka topic definition
     */
    @Bean
    public NewTopic behaviorEventsTopic(@Value("${app.behavior.kafka-topic:vibelo.user-behaviors}") String topic) {
        return TopicBuilder.name(topic)
                .partitions(6)
                .replicas(1)
                .config("retention.ms", "604800000")
                .build();
    }
}
