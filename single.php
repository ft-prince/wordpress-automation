<?php
/**
 * Single Post Template — blog articles.
 *
 * @package Servelens
 */

get_header();

while ( have_posts() ) :
    the_post();

    $categories = get_the_category();
    $primary    = ! empty( $categories ) ? $categories[0]->name : '';
?>

<!-- Post Hero -->
<section class="solution-hero">
    <div class="container">
        <div class="solution-hero-inner">
            <div class="solution-hero-text">
                <?php if ( $primary ) : ?>
                    <span class="section-badge"><?php echo esc_html( $primary ); ?></span>
                <?php endif; ?>
                <h1><?php the_title(); ?></h1>
                <p class="lead">
                    <?php echo esc_html( get_the_date() ); ?> &middot; <?php echo esc_html( get_the_author() ); ?>
                </p>
            </div>
        </div>
    </div>
</section>

<!-- Content + Sidebar -->
<section class="section-pad">
    <div class="container">
        <div class="solution-content-layout">

            <div class="solution-main">
                <?php if ( has_post_thumbnail() ) : ?>
                    <div class="solution-section">
                        <?php the_post_thumbnail( 'large', [ 'style' => 'width:100%; height:auto; border-radius: var(--border-radius-lg);' ] ); ?>
                    </div>
                <?php endif; ?>

                <div class="solution-section post-body">
                    <?php the_content(); ?>
                </div>

                <?php if ( has_tag() ) : ?>
                    <div class="solution-section">
                        <div class="usecase-chips">
                            <?php foreach ( get_the_tags() as $tag ) : ?>
                                <a class="usecase-chip" href="<?php echo esc_url( get_tag_link( $tag->term_id ) ); ?>">
                                    <?php echo esc_html( $tag->name ); ?>
                                </a>
                            <?php endforeach; ?>
                        </div>
                    </div>
                <?php endif; ?>
            </div>

            <aside class="solution-sidebar">
                <div class="sidebar-card" style="background: var(--color-primary); border-color: var(--color-primary);">
                    <h4 style="color:#fff;">Ready to Deploy?</h4>
                    <p style="font-size: var(--text-sm); color: rgba(255,255,255,0.85); margin-bottom: var(--space-4);">
                        Talk to our team about your specific requirements.
                    </p>
                    <a href="<?php echo esc_url( home_url( '/contact' ) ); ?>" class="btn btn-white btn-full">Request Demo</a>
                </div>

                <?php
                $recent = new WP_Query( [
                    'post_type'      => 'post',
                    'posts_per_page' => 5,
                    'post__not_in'   => [ get_the_ID() ],
                ] );
                if ( $recent->have_posts() ) :
                ?>
                <div class="sidebar-card">
                    <h4>Recent Articles</h4>
                    <ul class="sidebar-nav">
                        <?php while ( $recent->have_posts() ) : $recent->the_post(); ?>
                            <li>
                                <a href="<?php the_permalink(); ?>">
                                    <?php echo function_exists( 'servelens_icon' ) ? servelens_icon( 'arrow-right', 14 ) : ''; ?>
                                    <?php the_title(); ?>
                                </a>
                            </li>
                        <?php endwhile; wp_reset_postdata(); ?>
                    </ul>
                </div>
                <?php endif; ?>
            </aside>

        </div>
    </div>
</section>

<?php endwhile; ?>

<?php if ( function_exists( 'servelens_cta_section' ) ) servelens_cta_section(); ?>

<?php get_footer(); ?>