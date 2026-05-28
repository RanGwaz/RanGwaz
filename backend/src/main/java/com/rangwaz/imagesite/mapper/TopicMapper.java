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
 * Mapper for topics and image-topic bindings.
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
     * Binds a topic to an image.
     *
     * @param imageId image id
     * @param topicId topic id
     */
    @Insert("INSERT IGNORE INTO image_topics(image_id,topic_id) VALUES(#{imageId},#{topicId})")
    void bindImage(@Param("imageId") Long imageId, @Param("topicId") Long topicId);

    /**
     * Lists topics attached to an image.
     *
     * @param imageId image id
     * @return topics
     */
    @Select("""
            SELECT t.* FROM topics t
            JOIN image_topics it ON it.topic_id=t.id
            WHERE it.image_id=#{imageId}
            ORDER BY t.hot_score DESC
            """)
    List<TopicEntity> findByImageId(@Param("imageId") Long imageId);

    /**
     * Lists topics for a batch of images.
     *
     * @param imageIds image ids
     * @return image-topic projection rows
     */
    @Select({
            "<script>",
            "SELECT it.image_id AS image_id,t.id,t.name,t.slug,t.description,t.cover_url,t.post_count,t.follower_count,t.hot_score,t.created_at,t.updated_at",
            "FROM topics t",
            "JOIN image_topics it ON it.topic_id=t.id",
            "WHERE it.image_id IN",
            "<foreach collection='imageIds' item='id' open='(' separator=',' close=')'>#{id}</foreach>",
            "ORDER BY it.image_id,t.hot_score DESC,t.id",
            "</script>"
    })
    List<ImageTopicRow> findRowsByImageIds(@Param("imageIds") List<Long> imageIds);

    /**
     * Increments topic post count.
     *
     * @param topicId topic id
     */
    @Update("UPDATE topics SET post_count=post_count+1 WHERE id=#{topicId}")
    void incrementPostCount(@Param("topicId") Long topicId);

    /**
     * Projection for batch image-topic reads.
     */
    class ImageTopicRow extends TopicEntity {
        private Long imageId;

        public Long getImageId() {
            return imageId;
        }

        public void setImageId(Long imageId) {
            this.imageId = imageId;
        }
    }
}
