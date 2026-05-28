package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.TagEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for typed image tags.
 */
@Mapper
public interface TagMapper {
    /**
     * Inserts a tag.
     *
     * @param tag tag entity
     */
    @Insert("""
            INSERT INTO tags(name,type,slug)
            VALUES(#{name},#{type},#{slug})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(TagEntity tag);

    /**
     * Finds a tag by type and name.
     *
     * @param type tag type
     * @param name tag name
     * @return tag entity
     */
    @Select("SELECT * FROM tags WHERE type=#{type} AND name=#{name}")
    TagEntity findByTypeAndName(@Param("type") String type, @Param("name") String name);

    /**
     * Lists tags constrained by type.
     *
     * @param type tag type
     * @param limit maximum rows
     * @return tags
     */
    @Select("""
            SELECT * FROM tags
            WHERE type=#{type}
            ORDER BY type,name
            LIMIT #{limit}
            """)
    List<TagEntity> findByType(@Param("type") String type, @Param("limit") int limit);

    /**
     * Lists all tags.
     *
     * @param limit maximum rows
     * @return tags
     */
    @Select("""
            SELECT * FROM tags
            ORDER BY type,name
            LIMIT #{limit}
            """)
    List<TagEntity> findAll(@Param("limit") int limit);
}
