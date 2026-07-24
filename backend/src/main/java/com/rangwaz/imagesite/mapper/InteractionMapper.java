package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.ImageEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for user-image interaction state.
 */
@Mapper
public interface InteractionMapper {
    /**
     * Checks if an interaction is active.
     *
     * @param userId user id
     * @param imageId image id
     * @param type interaction type
     * @return active count
     */
    @Select("""
            SELECT COUNT(*) FROM user_interactions
            WHERE user_id=#{userId} AND image_id=#{imageId} AND interaction_type=#{type} AND active=1
            """)
    int countActive(@Param("userId") Long userId, @Param("imageId") Long imageId, @Param("type") String type);

    /**
     * Counts active interactions by type.
     *
     * @param userId user id
     * @param type interaction type
     * @return active count
     */
    @Select("""
            SELECT COUNT(*) FROM user_interactions
            WHERE user_id=#{userId} AND interaction_type=#{type} AND active=1
            """)
    long countActiveByType(@Param("userId") Long userId, @Param("type") String type);

    /**
     * Upserts interaction state.
     *
     * @param userId user id
     * @param imageId image id
     * @param type interaction type
     * @param active active flag
     */
    @Insert("""
            INSERT INTO user_interactions(user_id,image_id,interaction_type,active)
            VALUES(#{userId},#{imageId},#{type},#{active})
            ON DUPLICATE KEY UPDATE active=#{active},updated_at=NOW()
            """)
    void upsert(@Param("userId") Long userId, @Param("imageId") Long imageId, @Param("type") String type, @Param("active") boolean active);

    /**
     * Lists images with an active interaction, newest interaction first.
     *
     * @param userId user id
     * @param type interaction type
     * @param limit maximum rows
     * @return published images
     */
    @Select("""
            SELECT i.*
            FROM user_interactions ui
            JOIN images i ON i.id=ui.image_id
            WHERE ui.user_id=#{userId}
              AND ui.interaction_type=#{type}
              AND ui.active=1
              AND i.status='PUBLISHED'
            ORDER BY ui.updated_at DESC,ui.id DESC
            LIMIT #{limit}
            """)
    List<ImageEntity> findActiveImages(@Param("userId") Long userId, @Param("type") String type, @Param("limit") int limit);
    /**
     * Batch-loads active like and favorite states for feed cards.
     */
    @Select("""
            <script>
            SELECT image_id AS imageId, interaction_type AS interactionType
            FROM user_interactions
            WHERE user_id=#{userId}
              AND active=1
              AND interaction_type IN ('LIKE','FAVORITE')
              AND image_id IN
              <foreach collection="imageIds" item="imageId" open="(" separator="," close=")">
                #{imageId}
              </foreach>
            </script>
            """)
    List<InteractionStateRow> findActiveStates(@Param("userId") Long userId,
                                               @Param("imageIds") List<Long> imageIds);

    class InteractionStateRow {
        private Long imageId;
        private String interactionType;

        public Long getImageId() {
            return imageId;
        }

        public void setImageId(Long imageId) {
            this.imageId = imageId;
        }

        public String getInteractionType() {
            return interactionType;
        }

        public void setInteractionType(String interactionType) {
            this.interactionType = interactionType;
        }
    }

}
