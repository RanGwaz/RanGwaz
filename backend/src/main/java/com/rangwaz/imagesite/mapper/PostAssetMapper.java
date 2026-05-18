package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.PostAssetEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for post media assets.
 */
@Mapper
public interface PostAssetMapper {
    /**
     * Inserts a post asset.
     *
     * @param asset asset entity
     */
    @Insert("""
            INSERT INTO post_assets(post_id,object_key,file_url,file_type,thumb_url,width,height,sort_order)
            VALUES(#{postId},#{objectKey},#{fileUrl},#{fileType},#{thumbUrl},#{width},#{height},#{sortOrder})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(PostAssetEntity asset);

    /**
     * Lists assets for one post.
     *
     * @param postId post id
     * @return post assets
     */
    @Select("SELECT * FROM post_assets WHERE post_id=#{postId} ORDER BY sort_order,id")
    List<PostAssetEntity> findByPostId(@Param("postId") Long postId);
}
