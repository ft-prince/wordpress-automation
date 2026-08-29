<?php
/**
 * Plugin Name: Servelens SEO
 * Description: Meta description (custom field or excerpt), Open Graph, Twitter cards, canonical URL.
 * Version: 1.1
 *
 * Install: upload to wp-content/mu-plugins/ (create the folder if missing).
 * mu-plugins load automatically — no activation step, no admin screen to break.
 */

defined( 'ABSPATH' ) || exit;

// REST-editable meta description for every content type — lets template-driven
// pages (whose post_content is empty) still carry a hand-set description.
add_action( 'init', function () {
    foreach ( array( 'post', 'page', 'solution' ) as $type ) {
        register_post_meta( $type, 'servelens_seo_desc', array(
            'show_in_rest'  => true,
            'single'        => true,
            'type'          => 'string',
            'auth_callback' => function () { return current_user_can( 'edit_posts' ); },
        ) );
    }
} );

add_action( 'wp_head', function () {
    $desc  = '';
    $image = '';
    $url   = '';
    $title = wp_get_document_title();

    if ( is_singular() ) {
        $post  = get_queried_object();
        $url   = get_permalink( $post );
        $custom = get_post_meta( $post->ID, 'servelens_seo_desc', true );
        $desc  = $custom
            ? wp_strip_all_tags( $custom )
            : ( $post->post_excerpt
                ? wp_strip_all_tags( $post->post_excerpt )
                : wp_trim_words( wp_strip_all_tags( $post->post_content ), 25, '…' ) );
        if ( has_post_thumbnail( $post ) ) {
            $image = get_the_post_thumbnail_url( $post, 'large' );
        }
    } elseif ( is_home() || is_front_page() ) {
        $url  = home_url( '/' );
        $desc = get_bloginfo( 'description' );
    } elseif ( is_category() || is_tag() ) {
        $url  = get_term_link( get_queried_object() );
        $desc = wp_strip_all_tags( term_description() ) ?: get_bloginfo( 'description' );
    }

    $desc = mb_substr( trim( $desc ), 0, 160 );

    if ( $desc ) {
        printf( '<meta name="description" content="%s">' . "\n", esc_attr( $desc ) );
    }
    if ( $url ) {
        printf( '<link rel="canonical" href="%s">' . "\n", esc_url( $url ) );
        printf( '<meta property="og:url" content="%s">' . "\n", esc_url( $url ) );
    }
    printf( '<meta property="og:title" content="%s">' . "\n", esc_attr( $title ) );
    printf( '<meta property="og:type" content="%s">' . "\n", is_singular( 'post' ) ? 'article' : 'website' );
    printf( '<meta property="og:site_name" content="%s">' . "\n", esc_attr( get_bloginfo( 'name' ) ) );
    if ( $desc ) {
        printf( '<meta property="og:description" content="%s">' . "\n", esc_attr( $desc ) );
    }
    if ( $image ) {
        printf( '<meta property="og:image" content="%s">' . "\n", esc_url( $image ) );
    }
    echo '<meta name="twitter:card" content="' . ( $image ? 'summary_large_image' : 'summary' ) . '">' . "\n";

    // Article JSON-LD for posts — helps rich results.
    if ( is_singular( 'post' ) ) {
        $post   = get_queried_object();
        $schema = [
            '@context'      => 'https://schema.org',
            '@type'         => 'Article',
            'headline'      => get_the_title( $post ),
            'description'   => $desc,
            'datePublished' => get_the_date( 'c', $post ),
            'dateModified'  => get_the_modified_date( 'c', $post ),
            'author'        => [ '@type' => 'Organization', 'name' => get_bloginfo( 'name' ) ],
            'mainEntityOfPage' => $url,
        ];
        if ( $image ) {
            $schema['image'] = $image;
        }
        echo '<script type="application/ld+json">' . wp_json_encode( $schema, JSON_UNESCAPED_SLASHES ) . '</script>' . "\n";
    }
}, 5 );
