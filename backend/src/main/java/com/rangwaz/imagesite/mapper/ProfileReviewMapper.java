package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.ProfileReviewEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * Mapper for profile update review requests.
 */
@Mapper
public interface ProfileReviewMapper {
    /**
     * Inserts a profile review request.
     *
     * @param review review entity
     */
    @Insert("""
            INSERT INTO profile_update_reviews(user_id,nickname,avatar_url,background_url,bio,status)
            VALUES(#{userId},#{nickname},#{avatarUrl},#{backgroundUrl},#{bio},#{status})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(ProfileReviewEntity review);

    /**
     * Finds one review by id.
     *
     * @param id review id
     * @return review
     */
    @Select("SELECT * FROM profile_update_reviews WHERE id=#{id}")
    ProfileReviewEntity findById(@Param("id") Long id);

    /**
     * Finds latest review for a user.
     *
     * @param userId user id
     * @return latest review
     */
    @Select("""
            SELECT * FROM profile_update_reviews
            WHERE user_id=#{userId}
            ORDER BY created_at DESC,id DESC
            LIMIT 1
            """)
    ProfileReviewEntity findLatestByUser(@Param("userId") Long userId);

    /**
     * Lists review requests by status for manual moderation.
     *
     * @param status review status
     * @param limit maximum rows
     * @return review rows
     */
    @Select("""
            SELECT * FROM profile_update_reviews
            WHERE status=#{status}
            ORDER BY created_at ASC,id ASC
            LIMIT #{limit}
            """)
    List<ProfileReviewEntity> findByStatus(@Param("status") String status, @Param("limit") int limit);

    /**
     * Marks previous pending reviews as superseded.
     *
     * @param userId user id
     */
    @Update("""
            UPDATE profile_update_reviews
            SET status='SUPERSEDED',review_reason='用户提交了新的资料审核申请',reviewed_at=NOW()
            WHERE user_id=#{userId} AND status='PENDING_REVIEW'
            """)
    void supersedePending(@Param("userId") Long userId);

    /**
     * Updates review decision.
     *
     * @param id review id
     * @param status status
     * @param reason reason
     */
    @Update("""
            UPDATE profile_update_reviews
            SET status=#{status},review_reason=#{reason},reviewed_at=NOW()
            WHERE id=#{id}
            """)
    void updateDecision(@Param("id") Long id, @Param("status") String status, @Param("reason") String reason);
}
