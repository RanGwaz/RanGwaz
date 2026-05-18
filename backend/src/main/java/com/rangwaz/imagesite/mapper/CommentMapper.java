package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.CommentEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for post comments.
 */
@Mapper
public interface CommentMapper {
    /**
     * Inserts a comment.
     *
     * @param comment comment entity
     */
    @Insert("""
            INSERT INTO comments(post_id,author_id,parent_comment_id,content,status)
            VALUES(#{postId},#{authorId},#{parentCommentId},#{content},#{status})
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
     * Counts visible comments for a post.
     *
     * @param postId post id
     * @return comment count
     */
    @Select("SELECT COUNT(*) FROM comments WHERE post_id=#{postId} AND status='VISIBLE'")
    long countByPostId(@Param("postId") Long postId);

    /**
     * Pages visible comments for a post.
     *
     * @param postId post id
     * @param offset row offset
     * @param size page size
     * @return comments
     */
    @Select("""
            SELECT * FROM comments
            WHERE post_id=#{postId} AND status='VISIBLE'
            ORDER BY created_at DESC,id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<CommentEntity> pageByPostId(@Param("postId") Long postId, @Param("offset") int offset, @Param("size") int size);
}
