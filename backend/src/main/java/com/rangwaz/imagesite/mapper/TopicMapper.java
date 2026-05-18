package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.TopicEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * Mapper for topics and post-topic bindings.
 */
@Mapper
public interface TopicMapper {
    /**
     * Inserts a topic.
     *
     * @param topic topic entity
     */
    @Insert("""
            INSERT INTO topics(name,slug,description,cover_url,post_count,follower_count,hot_score)
            VALUES(#{name},#{slug},#{description},#{coverUrl},#{postCount},#{followerCount},#{hotScore})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(TopicEntity topic);

    /**
     * Finds a topic by name.
     *
     * @param name topic name
     * @return topic entity
     */
    @Select("SELECT * FROM topics WHERE name=#{name}")
    TopicEntity findByName(@Param("name") String name);

    /**
     * Counts topics.
     *
     * @return topic count
     */
    @Select("SELECT COUNT(*) FROM topics")
    long countTopics();

    /**
     * Lists trending topics.
     *
     * @param limit maximum rows
     * @return topics
     */
    @Select("SELECT * FROM topics ORDER BY hot_score DESC,post_count DESC LIMIT #{limit}")
    List<TopicEntity> trending(@Param("limit") int limit);

    /**
     * Searches topics by name.
     *
     * @param keyword search keyword
     * @param limit maximum rows
     * @return topics
     */
    @Select("""
            SELECT * FROM topics
            WHERE name LIKE CONCAT('%',#{keyword},'%') OR slug LIKE CONCAT('%',#{keyword},'%')
            ORDER BY hot_score DESC
            LIMIT #{limit}
            """)
    List<TopicEntity> search(@Param("keyword") String keyword, @Param("limit") int limit);

    /**
     * Binds a topic to a post.
     *
     * @param postId post id
     * @param topicId topic id
     */
    @Insert("INSERT IGNORE INTO post_topics(post_id,topic_id) VALUES(#{postId},#{topicId})")
    void bindPost(@Param("postId") Long postId, @Param("topicId") Long topicId);

    /**
     * Lists topics attached to a post.
     *
     * @param postId post id
     * @return topics
     */
    @Select("""
            SELECT t.* FROM topics t
            JOIN post_topics pt ON pt.topic_id=t.id
            WHERE pt.post_id=#{postId}
            ORDER BY t.hot_score DESC
            """)
    List<TopicEntity> findByPostId(@Param("postId") Long postId);

    /**
     * Increments topic post count.
     *
     * @param topicId topic id
     */
    @Update("UPDATE topics SET post_count=post_count+1,hot_score=hot_score+0.6 WHERE id=#{topicId}")
    void incrementPostCount(@Param("topicId") Long topicId);
}
