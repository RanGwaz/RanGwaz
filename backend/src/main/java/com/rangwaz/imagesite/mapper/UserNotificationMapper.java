package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.UserNotificationEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for in-app notifications.
 */
@Mapper
public interface UserNotificationMapper {
    /**
     * Inserts one notification.
     *
     * @param notification notification entity
     */
    @Insert("""
            INSERT INTO user_notifications(user_id,type,title,content,target_type,target_id,is_read)
            VALUES(#{userId},#{type},#{title},#{content},#{targetType},#{targetId},#{read})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(UserNotificationEntity notification);

    /**
     * Lists recent notifications for one user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return notifications
     */
    @Select("""
            SELECT id,user_id,type,title,content,target_type,target_id,is_read AS `read`,created_at
            FROM user_notifications
            WHERE user_id=#{userId}
            ORDER BY created_at DESC,id DESC
            LIMIT #{limit}
            """)
    List<UserNotificationEntity> findByUser(@Param("userId") Long userId, @Param("limit") int limit);
}
