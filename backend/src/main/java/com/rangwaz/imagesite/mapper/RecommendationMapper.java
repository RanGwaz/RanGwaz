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
}
