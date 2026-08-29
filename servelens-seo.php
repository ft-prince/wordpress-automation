<?php
/**
 * Plugin Name: Site Automation Helpers
 * Description: Meta description (custom field or excerpt), Open Graph, Twitter cards, canonical URL.
 * Version: 1.2
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


// ── Theme file CRUD for the automation dashboard ──────────────────────────
// Admin-only (edit_themes), active theme directory only, whitelisted extensions.
// PHP files are syntax-checked before writing; the previous version is backed up.

function autodash_theme_path( $rel ) {
    $root = wp_normalize_path( get_stylesheet_directory() );
    $rel  = ltrim( (string) $rel, '/' );
    if ( '' === $rel || false !== strpos( $rel, '..' ) ) {
        return null;
    }
    $ext = strtolower( pathinfo( $rel, PATHINFO_EXTENSION ) );
    if ( ! in_array( $ext, array( 'php', 'css', 'js', 'txt', 'md', 'html' ), true ) ) {
        return null;
    }
    $full = wp_normalize_path( $root . '/' . $rel );
    if ( 0 !== strpos( $full, $root . '/' ) && $full !== $root ) {
        return null;
    }
    return $full;
}

function autodash_backup_file( $full ) {
    if ( ! file_exists( $full ) ) {
        return;
    }
    $up  = wp_upload_dir();
    $dir = $up['basedir'] . '/automation-backups';
    if ( ! is_dir( $dir ) ) {
        wp_mkdir_p( $dir );
    }
    @copy( $full, $dir . '/' . basename( $full ) . '.' . gmdate( 'Ymd-His' ) . '.bak' );
}

function autodash_php_syntax_ok( $code, &$error ) {
    try {
        token_get_all( $code, TOKEN_PARSE );
        return true;
    } catch ( ParseError $e ) {
        $error = $e->getMessage() . ' on line ' . $e->getLine();
        return false;
    }
}

add_action( 'rest_api_init', function () {
    $perm = function () { return current_user_can( 'edit_themes' ); };

    register_rest_route( 'automation/v1', '/theme-files', array(
        'methods'             => 'GET',
        'permission_callback' => $perm,
        'callback'            => function () {
            $root  = wp_normalize_path( get_stylesheet_directory() );
            $out   = array();
            $iter  = new RecursiveIteratorIterator( new RecursiveDirectoryIterator( $root, FilesystemIterator::SKIP_DOTS ) );
            foreach ( $iter as $f ) {
                $rel = ltrim( substr( wp_normalize_path( $f->getPathname() ), strlen( $root ) ), '/' );
                if ( null === autodash_theme_path( $rel ) ) {
                    continue;
                }
                $out[] = array( 'path' => $rel, 'size' => $f->getSize(), 'modified' => gmdate( 'c', $f->getMTime() ) );
            }
            usort( $out, function ( $a, $b ) { return strcmp( $a['path'], $b['path'] ); } );
            return array( 'theme' => get_stylesheet(), 'files' => $out );
        },
    ) );

    register_rest_route( 'automation/v1', '/theme-file', array(
        array(
            'methods'             => 'GET',
            'permission_callback' => $perm,
            'callback'            => function ( $req ) {
                $full = autodash_theme_path( $req->get_param( 'path' ) );
                if ( ! $full || ! file_exists( $full ) ) {
                    return new WP_Error( 'not_found', 'File not found', array( 'status' => 404 ) );
                }
                return array( 'path' => $req->get_param( 'path' ), 'content' => file_get_contents( $full ) );
            },
        ),
        array(
            'methods'             => 'POST',
            'permission_callback' => $perm,
            'callback'            => function ( $req ) {
                $full = autodash_theme_path( $req->get_param( 'path' ) );
                if ( ! $full ) {
                    return new WP_Error( 'bad_path', 'Path not allowed', array( 'status' => 400 ) );
                }
                $content = (string) $req->get_param( 'content' );
                $err     = '';
                if ( 'php' === strtolower( pathinfo( $full, PATHINFO_EXTENSION ) )
                    && ! autodash_php_syntax_ok( $content, $err ) ) {
                    return new WP_Error( 'syntax_error', 'PHP syntax error: ' . $err, array( 'status' => 400 ) );
                }
                autodash_backup_file( $full );
                $dir = dirname( $full );
                if ( ! is_dir( $dir ) ) {
                    wp_mkdir_p( $dir );
                }
                if ( false === file_put_contents( $full, $content ) ) {
                    return new WP_Error( 'write_failed', 'Could not write file', array( 'status' => 500 ) );
                }
                return array( 'saved' => true, 'path' => $req->get_param( 'path' ), 'bytes' => strlen( $content ) );
            },
        ),
        array(
            'methods'             => 'DELETE',
            'permission_callback' => $perm,
            'callback'            => function ( $req ) {
                $full = autodash_theme_path( $req->get_param( 'path' ) );
                if ( ! $full || ! file_exists( $full ) ) {
                    return new WP_Error( 'not_found', 'File not found', array( 'status' => 404 ) );
                }
                if ( in_array( basename( $full ), array( 'functions.php', 'index.php', 'style.css' ), true ) ) {
                    return new WP_Error( 'protected', 'This core theme file cannot be deleted', array( 'status' => 400 ) );
                }
                autodash_backup_file( $full );
                unlink( $full );
                return array( 'deleted' => true );
            },
        ),
    ) );
} );
