package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.CommentEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for image comments.
 */
@Mapper
public interface CommentMapper {
    /**
     * Inserts a comment.
     *
     * @param comment comment entity
     */
    @Insert("""
            INSERT INTO comments(image_id,author_id,parent_comment_id,content,status)
            VALUES(#{imageId},#{authorId},#{parentCommentId},#{content},#{status})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(CommentEntity comment);

    /**
     * Finds a comment by id.
     *
     * @param id comment id
     * @return comment entity
     */
    @Select("SELECT * FROM comments WHERE id=#{id}")
    CommentEntity findById(@Param("id") Long id);

    /**
     * Counts visible comments for an image.
     *
     * @param imageId image id
     * @return comment count
     */
    @Select("SELECT COUNT(*) FROM comments WHERE image_id=#{imageId} AND status='VISIBLE'")
    long countByImageId(@Param("imageId") Long imageId);

    /**
     * Pages visible comments for an image.
     *
     * @param imageId image id
     * @param offset row offset
     * @param size page size
     * @return comments
     */
    @Select("""
            SELECT * FROM comments
            WHERE image_id=#{imageId} AND status='VISIBLE'
            ORDER BY created_at DESC,id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<CommentEntity> pageByImageId(@Param("imageId") Long imageId, @Param("offset") int offset, @Param("size") int size);
}
