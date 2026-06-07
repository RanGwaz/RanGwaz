package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.ImageEntity;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for recommendation candidate recall and ranking.
 */
@Mapper
public interface RecommendationMapper {
    /**
     * Recalls images from tags attached to the user's positive behavior history.
     *
     * @param userId user id
     * @param size maximum rows
     * @return image rows
     */
    @Select("""
            WITH seed_events AS (
              SELECT ub.image_id,
                     MAX(
                       CASE ub.behavior_type
                         WHEN 'favorite' THEN 60
                         WHEN 'like' THEN 45
                         WHEN 'comment' THEN 40
                         WHEN 'share' THEN 40
                         WHEN 'click' THEN 25
                         WHEN 'view' THEN 15
                         ELSE 1
                       END
                     ) AS behavior_weight,
                     MAX(ub.created_at) AS latest_at
              FROM user_behaviors ub
              WHERE ub.user_id=#{userId}
                AND ub.behavior_type IN ('favorite','like','comment','share','click','view')
                AND ub.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
              GROUP BY ub.image_id
              ORDER BY behavior_weight DESC, latest_at DESC
              LIMIT 80
            ),
            seed_tags AS (
              SELECT it.tag_id,
                     SUM(seed_events.behavior_weight * COALESCE(it.confidence,1)) AS affinity
              FROM seed_events
              JOIN image_tags it ON it.image_id=seed_events.image_id
              GROUP BY it.tag_id
              ORDER BY affinity DESC
              LIMIT 80
            )
            SELECT i.*
            FROM seed_tags
            JOIN image_tags it ON it.tag_id=seed_tags.tag_id
            JOIN images i ON i.id=it.image_id AND i.status='PUBLISHED'
            LEFT JOIN seed_events ON seed_events.image_id=i.id
            WHERE seed_events.image_id IS NULL
            GROUP BY i.id
            ORDER BY
              SUM(seed_tags.affinity * COALESCE(it.confidence,1)) DESC,
              i.hot_score DESC,
              i.published_at DESC,
              i.id DESC
            LIMIT #{size}
            """)
    List<ImageEntity> selectUserTagRecall(@Param("userId") Long userId, @Param("size") int size);

    /**
     * Recalls images from categories in the user's positive behavior history.
     *
     * @param userId user id
     * @param size maximum rows
     * @return image rows
     */
    @Select("""
            WITH seed_events AS (
              SELECT ub.image_id,
                     MAX(
                       CASE ub.behavior_type
                         WHEN 'favorite' THEN 60
                         WHEN 'like' THEN 45
                         WHEN 'comment' THEN 40
                         WHEN 'share' THEN 40
                         WHEN 'click' THEN 25
                         WHEN 'view' THEN 15
                         ELSE 1
                       END
                     ) AS behavior_weight,
                     MAX(ub.created_at) AS latest_at
              FROM user_behaviors ub
              WHERE ub.user_id=#{userId}
                AND ub.behavior_type IN ('favorite','like','comment','share','click','view')
                AND ub.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
              GROUP BY ub.image_id
              ORDER BY behavior_weight DESC, latest_at DESC
              LIMIT 80
            ),
            seed_categories AS (
              SELECT i.main_category_id,
                     SUM(seed_events.behavior_weight) AS affinity
              FROM seed_events
              JOIN images i ON i.id=seed_events.image_id
              WHERE i.main_category_id IS NOT NULL
              GROUP BY i.main_category_id
              ORDER BY affinity DESC
              LIMIT 20
            )
            SELECT i.*
            FROM seed_categories
            JOIN images i ON i.main_category_id=seed_categories.main_category_id AND i.status='PUBLISHED'
            LEFT JOIN seed_events ON seed_events.image_id=i.id
            WHERE seed_events.image_id IS NULL
            ORDER BY
              seed_categories.affinity DESC,
              i.hot_score DESC,
              i.published_at DESC,
              i.id DESC
            LIMIT #{size}
            """)
    List<ImageEntity> selectUserCategoryRecall(@Param("userId") Long userId, @Param("size") int size);

    /**
     * Recalls images from lightweight topics attached to the user's positive behavior history.
     *
     * @param userId user id
     * @param size maximum rows
     * @return image rows
     */
    @Select("""
            WITH seed_events AS (
              SELECT ub.image_id,
                     MAX(
                       CASE ub.behavior_type
                         WHEN 'favorite' THEN 60
                         WHEN 'like' THEN 45
                         WHEN 'comment' THEN 40
                         WHEN 'share' THEN 40
                         WHEN 'click' THEN 25
                         WHEN 'view' THEN 15
                         ELSE 1
                       END
                     ) AS behavior_weight,
                     MAX(ub.created_at) AS latest_at
              FROM user_behaviors ub
              WHERE ub.user_id=#{userId}
                AND ub.behavior_type IN ('favorite','like','comment','share','click','view')
                AND ub.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
              GROUP BY ub.image_id
              ORDER BY behavior_weight DESC, latest_at DESC
              LIMIT 80
            ),
            seed_topics AS (
              SELECT it.topic_id,
                     SUM(seed_events.behavior_weight) AS affinity
              FROM seed_events
              JOIN image_topics it ON it.image_id=seed_events.image_id
              GROUP BY it.topic_id
              ORDER BY affinity DESC
              LIMIT 50
            )
            SELECT i.*
            FROM seed_topics
            JOIN image_topics it ON it.topic_id=seed_topics.topic_id
            JOIN images i ON i.id=it.image_id AND i.status='PUBLISHED'
            LEFT JOIN seed_events ON seed_events.image_id=i.id
            WHERE seed_events.image_id IS NULL
            GROUP BY i.id
            ORDER BY
              SUM(seed_topics.affinity) DESC,
              i.hot_score DESC,
              i.published_at DESC,
              i.id DESC
            LIMIT #{size}
            """)
    List<ImageEntity> selectUserTopicRecall(@Param("userId") Long userId, @Param("size") int size);

    /**
     * Recalls fresh images from followed authors.
     *
     * @param userId user id
     * @param size maximum rows
     * @return image rows
     */
    @Select("""
            SELECT i.*
            FROM follows f
            JOIN images i ON i.author_id=f.followee_id AND i.status='PUBLISHED'
            WHERE f.follower_id=#{userId}
            ORDER BY i.published_at DESC,i.hot_score DESC,i.id DESC
            LIMIT #{size}
            """)
    List<ImageEntity> selectFollowedAuthorRecall(@Param("userId") Long userId, @Param("size") int size);

    /**
     * Selects a cold-start feed ranked by quality, freshness, and engagement.
     *
     * @param offset row offset
     * @param size page size
     * @return image rows
     */
    @Select("""
            WITH tag_counts AS (
              SELECT image_id,COUNT(*) AS tag_count
              FROM image_tags
              GROUP BY image_id
            )
            SELECT i.*
            FROM images i
            LEFT JOIN tag_counts tc ON tc.image_id=i.id
            WHERE i.status='PUBLISHED'
            ORDER BY
              (
                COALESCE(i.hot_score,0) * 0.35
                + LEAST(COALESCE(tc.tag_count,0),12) * 0.12
                + CASE WHEN i.description IS NULL OR i.description='' THEN 0 ELSE 0.4 END
                + 24 / (TIMESTAMPDIFF(HOUR,i.published_at,NOW()) + 24)
              ) DESC,
              i.published_at DESC,
              i.id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<ImageEntity> selectColdStart(@Param("offset") int offset, @Param("size") int size);

    /**
     * Selects images similar to one image from tags, category, ratio, and engagement.
     *
     * @param imageId source image id
     * @param offset row offset
     * @param size page size
     * @return image rows
     */
    @Select("""
            WITH source_image AS (
              SELECT id,main_category_id,ratio
              FROM images
              WHERE id=#{imageId}
            ),
            tag_counts AS (
              SELECT image_id,COUNT(*) AS tag_count
              FROM image_tags
              GROUP BY image_id
            )
            SELECT i.*
            FROM source_image src
            JOIN images i ON i.status='PUBLISHED' AND i.id<>src.id
            LEFT JOIN image_tags source_tags ON source_tags.image_id=src.id
            LEFT JOIN image_tags it ON it.image_id=i.id AND it.tag_id=source_tags.tag_id
            LEFT JOIN tag_counts tc ON tc.image_id=i.id
            GROUP BY i.id,src.main_category_id,src.ratio
            ORDER BY
              (
                COALESCE(SUM(CASE WHEN it.tag_id IS NULL THEN 0 ELSE COALESCE(it.confidence,1) END),0) * 3.0
                + CASE WHEN i.main_category_id IS NOT NULL AND i.main_category_id=src.main_category_id THEN 2.2 ELSE 0 END
                + CASE WHEN i.ratio IS NOT NULL AND i.ratio=src.ratio THEN 0.6 ELSE 0 END
                + COALESCE(i.hot_score,0) * 0.25
                + LEAST(COALESCE(tc.tag_count,0),12) * 0.04
              ) DESC,
              i.published_at DESC,
              i.id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<ImageEntity> selectSimilarByMetadata(@Param("imageId") Long imageId,
                                              @Param("offset") int offset,
                                              @Param("size") int size);

    /**
     * Stable fallback for detail-page related feed when vector or rich metadata recall is not enough.
     *
     * @param imageId source image id
     * @param offset row offset
     * @param size page size
     * @return image rows
     */
    @Select("""
            WITH source_image AS (
              SELECT id,main_category_id,ratio
              FROM images
              WHERE id=#{imageId}
            )
            SELECT i.*
            FROM source_image src
            JOIN images i ON i.status='PUBLISHED' AND i.id<>src.id
            ORDER BY
              (
                CASE WHEN i.main_category_id IS NOT NULL AND i.main_category_id=src.main_category_id THEN 2.0 ELSE 0 END
                + CASE WHEN i.ratio IS NOT NULL AND i.ratio=src.ratio THEN 0.7 ELSE 0 END
                + COALESCE(i.hot_score,0) * 0.22
                + 24 / (TIMESTAMPDIFF(HOUR,i.published_at,NOW()) + 24)
              ) DESC,
              i.published_at DESC,
              i.id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<ImageEntity> selectSimilarFallback(@Param("imageId") Long imageId,
                                            @Param("offset") int offset,
                                            @Param("size") int size);
}
