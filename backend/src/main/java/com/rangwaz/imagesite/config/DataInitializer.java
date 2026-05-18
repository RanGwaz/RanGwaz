package com.rangwaz.imagesite.config;

import com.rangwaz.imagesite.common.auth.PasswordHasher;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.PostEntity;
import com.rangwaz.imagesite.entity.TopicEntity;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.PostMapper;
import com.rangwaz.imagesite.mapper.TopicMapper;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.PostService;
import com.rangwaz.imagesite.service.TopicService;
import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Random;

/**
 * Seeds the rebuilt development database with realistic random-image content.
 */
@Component
public class DataInitializer implements CommandLineRunner {
    private final UserMapper userMapper;
    private final TopicMapper topicMapper;
    private final PostMapper postMapper;
    private final TopicService topicService;
    private final PostService postService;
    private final JdbcTemplate jdbcTemplate;

    /**
     * Creates the data initializer.
     *
     * @param userMapper user mapper
     * @param topicMapper topic mapper
     * @param postMapper post mapper
     * @param topicService topic service
     * @param postService post service
     * @param jdbcTemplate JDBC template
     */
    public DataInitializer(UserMapper userMapper,
                           TopicMapper topicMapper,
                           PostMapper postMapper,
                           TopicService topicService,
                           PostService postService,
                           JdbcTemplate jdbcTemplate) {
        this.userMapper = userMapper;
        this.topicMapper = topicMapper;
        this.postMapper = postMapper;
        this.topicService = topicService;
        this.postService = postService;
        this.jdbcTemplate = jdbcTemplate;
    }

    /**
     * Seeds users, topics, posts, and recommendation feature placeholders.
     *
     * @param args command-line args
     */
    @Override
    public void run(String... args) {
        if (userMapper.countUsers() > 0 || postMapper.countPublished() > 0) return;
        List<UserEntity> users = seedUsers();
        seedTopics();
        seedPosts(users);
        seedFeatureRows();
    }

    /**
     * Seeds local users.
     *
     * @return created users
     */
    private List<UserEntity> seedUsers() {
        List<UserEntity> users = List.of(
                user("mira", "小米在旅行", "旅行博主 | 风景记录者", "travel"),
                user("caca", "卡卡要变强", "健身达人 | 自律生活", "fitness"),
                user("milk", "奶茶不加糖", "宠物日常和居家灵感", "pet"),
                user("keycap", "键盘侠K", "数码玩家 | 桌面搭建", "tech"),
                user("deer", "一只鹿鹿", "穿搭博主 | 分享日常", "style")
        );
        users.forEach(userMapper::insert);
        return users;
    }

    /**
     * Builds a seed user.
     *
     * @param username username
     * @param nickname nickname
     * @param bio bio
     * @param seed avatar seed
     * @return user entity
     */
    private UserEntity user(String username, String nickname, String bio, String seed) {
        UserEntity user = new UserEntity();
        user.setUsername(username);
        user.setPasswordHash(PasswordHasher.hash("123456"));
        user.setNickname(nickname);
        user.setAvatarUrl("https://api.dicebear.com/9.x/adventurer/svg?seed=" + seed);
        user.setBackgroundUrl("https://picsum.photos/seed/bg-" + seed + "/1200/360");
        user.setBio(bio);
        user.setStatus("ACTIVE");
        return user;
    }

    /**
     * Seeds default topics.
     */
    private void seedTopics() {
        List<String> topics = List.of("旅行碎片", "圣托里尼", "日落", "宠物日常", "健身打卡", "今日美食", "穿搭日记", "桌面改造", "摄影", "家居灵感", "校园生活", "咖啡时光");
        topics.forEach(topicService::getOrCreate);
    }

    /**
     * Seeds image posts with deterministic random dimensions.
     *
     * @param users created users
     */
    private void seedPosts(List<UserEntity> users) {
        Random random = new Random(42);
        List<String> titles = List.of(
                "圣托里尼的日落，永远看不够的浪漫时刻",
                "今天也是被治愈的一天",
                "沉浸式肩背训练，今日份挥汗",
                "桌面升级完成，RGB氛围感拉满",
                "周末做的日式豚骨拉面",
                "阳光刚好，记录一套舒服穿搭",
                "咖啡、书和一个安静的下午",
                "雪山清晨的第一束光",
                "小朋友认真搭积木的样子太可爱",
                "卧室换了新窗帘，整个房间都温柔了"
        );
        List<String> contents = List.of(
                "海风、日落和蓝顶教堂，这一刻时间慢了下来。",
                "把普通的一天拍成喜欢的样子，也算认真生活。",
                "记录训练过程，坚持比完美更重要。",
                "整理线材之后，桌面终于清爽了不少。",
                "汤头浓郁，叉烧刚好，幸福感满格。"
        );
        for (int i = 0; i < 72; i++) {
            UserEntity user = users.get(i % users.size());
            int width = 480 + random.nextInt(180);
            int height = 560 + random.nextInt(420);
            String seed = "rangwaz-" + i;
            String image = "https://picsum.photos/seed/" + seed + "/" + width + "/" + height;
            String title = titles.get(i % titles.size());
            String content = contents.get(i % contents.size());
            List<String> topics = List.of(topicName(i), topicName(i + 3));
            postService.create(
                    user.getId(),
                    new ApiDtos.CreatePostRequest(
                            title,
                            content,
                            "image",
                            List.of(image),
                            topics,
                            topics,
                            List.of(new ApiDtos.PostAssetRequest(seed, image, "image", image, width, height, 0))
                    )
            );
            PostEntity post = postMapper.findById((long) i + 1);
            if (post != null) {
                jdbcTemplate.update(
                        "UPDATE posts SET like_count=?,favorite_count=?,comment_count=?,share_count=?,view_count=?,hot_score=?,published_at=? WHERE id=?",
                        120 + random.nextInt(880),
                        30 + random.nextInt(240),
                        8 + random.nextInt(58),
                        random.nextInt(120),
                        600 + random.nextInt(5200),
                        BigDecimal.valueOf(20 + random.nextDouble() * 100),
                        LocalDateTime.now().minusHours(i * 3L),
                        post.getId()
                );
            }
        }
    }

    /**
     * Resolves a deterministic topic name.
     *
     * @param index index
     * @return topic name
     */
    private String topicName(int index) {
        List<String> topics = List.of("旅行碎片", "圣托里尼", "日落", "宠物日常", "健身打卡", "今日美食", "穿搭日记", "桌面改造", "摄影", "家居灵感", "校园生活", "咖啡时光");
        return topics.get(Math.floorMod(index, topics.size()));
    }

    /**
     * Seeds feature rows that future recommendation workers can update.
     */
    private void seedFeatureRows() {
        jdbcTemplate.update("""
                INSERT INTO post_recommendation_features(post_id,topic_vector,visual_embedding_ref,quality_score,freshness_score,engagement_score)
                SELECT id,JSON_ARRAY(0.2,0.4,0.6),CONCAT('seed-embedding-',id),hot_score/100,0.5,hot_score/120
                FROM posts
                """);
    }
}
