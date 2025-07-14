# OpenCitations Token Request Plugin

WordPress plugin for generating OpenCitations API access tokens with bot protection.

## Requirements

- WordPress 5.0+
- PHP 7.4+ with Redis extension
- Redis server
- hCaptcha account

## Installation

### 1. Install Plugin

Upload plugin files to WordPress (file at the bottom of this file):

```bash
/wp-content/plugins/opencitations-token-request/
└── opencitations-token-request.php
```

Set correct permissions:

```bash
chown -R www-data:www-data /wp-content/plugins/opencitations-token-request/
chmod 755 /wp-content/plugins/opencitations-token-request/
chmod 644 /wp-content/plugins/opencitations-token-request/opencitations-token-request.php
```

Activate the plugin in WordPress admin.

### 2. Install PHP Redis Extension

**For Kubernetes deployments**, add to your WordPress deployment:

```yaml
lifecycle:
  postStart:
    exec:
      command:
        - /bin/bash
        - -c
        - |
          apt-get update
          apt-get install -y sendmail
          pecl install redis
          docker-php-ext-enable redis
          service apache2 reload
```

**For traditional servers:**

```bash
apt-get install php-redis
service apache2 restart
```

### 3. Configure hCaptcha

1. Register at [hCaptcha](https://hcaptcha.com)
2. Create new site with your domain
3. Copy Site Key and Secret Key
4. Add keys in WordPress: Settings → OpenCitations Token

### 4. Configure Plugin

Go to Settings → OpenCitations Token and set:

- **Redis Host**: Your Redis server (e.g., `redis-service.default.svc.cluster.local`)
- **Redis Port**: 6379
- **Redis Password**: If required
- **From Email**: Sender email address
- **SMTP Settings**: For reliable email delivery (optional but recommended)

### 5. Add Form to Page

Insert shortcode in any page or post:

```
[opencitations_token_form]
```

## SMTP Configuration (Recommended)

For Gmail:
- Host: smtp.gmail.com
- Port: 587
- Security: TLS
- Username: your.email@gmail.com
- Password: App-specific password

## Testing

Use the admin panel buttons to test:
- Redis connection
- Email delivery

Generated tokens format: `UUID-EPOCHTIME`
Example: `457ce675-afbd-47c5-9218-192bbc9d024f-1748350084`

## opencitations-token-request.php file


```php
<?php
/**
 * Plugin Name: OpenCitations Token Request
 * Plugin URI: https://opencitations.net
 * Description: Module for requesting OpenCitations tokens with hCaptcha verification and Redis storage
 * Version: 2.0.2
 * License: CC0
 */

// Prevent direct access
if (!defined('ABSPATH')) {
    exit;
}

class OpenCitationsTokenRequest {

    private $hcaptcha_site_key;
    private $hcaptcha_secret_key;
    private $redis_host;
    private $redis_port;
    private $redis_password;
    private $from_email;
    private $from_name;
    private $smtp_host;
    private $smtp_port;
    private $smtp_user;
    private $smtp_password;
    private $smtp_secure;
    private $backup_emails; // NEW: backup email addresses

    public function __construct() {
        add_action('init', array($this, 'init'));
        add_action('wp_enqueue_scripts', array($this, 'enqueue_scripts'));
        add_action('wp_ajax_request_opencitations_token', array($this, 'handle_token_request'));
        add_action('wp_ajax_nopriv_request_opencitations_token', array($this, 'handle_token_request'));
        add_shortcode('opencitations_token_form', array($this, 'display_form'));
        add_action('admin_menu', array($this, 'add_admin_menu'));

        // NEW: Add cron hooks for monthly backup
        add_action('opencitations_monthly_backup', array($this, 'send_monthly_backup'));

        // Load configuration
        $this->load_config();
    }

    public function init() {
        // Plugin initialization
        // NEW: Schedule monthly backup if not already scheduled
        if (!wp_next_scheduled('opencitations_monthly_backup')) {
            wp_schedule_event(strtotime('first day of next month 00:00:00'), 'monthly', 'opencitations_monthly_backup');
        }
    }

    private function load_config() {
        $this->hcaptcha_site_key = get_option('oct_hcaptcha_site_key', '');
        $this->hcaptcha_secret_key = get_option('oct_hcaptcha_secret_key', '');
        $this->redis_host = get_option('oct_redis_host', 'redis-service.default.svc.cluster.local');
        $this->redis_port = get_option('oct_redis_port', '6379');
        $this->redis_password = get_option('oct_redis_password', '');
        $this->from_email = get_option('oct_from_email', get_option('admin_email'));
        $this->from_name = get_option('oct_from_name', get_bloginfo('name'));
        $this->smtp_host = get_option('oct_smtp_host', '');
        $this->smtp_port = get_option('oct_smtp_port', '587');
        $this->smtp_user = get_option('oct_smtp_user', '');
        $this->smtp_password = get_option('oct_smtp_password', '');
        $this->smtp_secure = get_option('oct_smtp_secure', 'tls');
        $this->backup_emails = get_option('oct_backup_emails', ''); // NEW
    }

    public function enqueue_scripts() {
        // Load hCaptcha script
        wp_enqueue_script('hcaptcha', 'https://hcaptcha.com/1/api.js', array(), '1.0.0', true);

        // Custom script localization
        wp_enqueue_script('jquery');
        wp_localize_script('jquery', 'oct_ajax', array(
            'ajax_url' => admin_url('admin-ajax.php'),
            'nonce' => wp_create_nonce('oct_nonce')
        ));
    }

    public function display_form($atts) {
        $atts = shortcode_atts(array(), $atts, 'opencitations_token_form');

        ob_start();
        ?>
        <div id="opencitations-token-container">
            <div class="oct-form-wrapper">
                <h3 class="oct-title">
                    Access Token Request
                </h3>
                <p class="oct-description">Enter your email address to receive your personal OpenCitations access token.</p>

                <form id="opencitations-token-form" method="post">
                    <div class="oct-form-group">
                        <label for="oct-email">Email Address *</label>
                        <input type="email" id="oct-email" name="email" required
                               placeholder="your.email@example.com" class="oct-input">
                        <div class="oct-email-error" style="display:none;"></div>
                    </div>

                    <div class="oct-form-group">
                        <div class="h-captcha" data-sitekey="<?php echo esc_attr($this->hcaptcha_site_key); ?>"></div>
                        <div class="oct-captcha-error" style="display:none;"></div>
                    </div>

                    <div class="oct-form-group">
                        <button type="submit" class="oct-submit-btn" id="oct-submit-btn">
                            <span class="oct-btn-text">Request Token</span>
                            <span class="oct-loading" style="display:none;">Processing...</span>
                        </button>
                    </div>

                    <div id="oct-message" class="oct-message" style="display:none;"></div>
                </form>

                <div class="oct-privacy-note">
                    <small>
                        <strong>Privacy Notice:</strong> Your email address will only be used to send you the access token.
                        We do not store your email or any personal information permanently.
                    </small>
                </div>
            </div>
        </div>

        <style>
        .oct-form-wrapper {
            max-width: 500px;
            margin: 20px auto;
            padding: 30px;
            background: #fff;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }

        .oct-title {
            text-align: center;
            font-size: 24px;
            margin-bottom: 10px;
            color: #333;
        }

        .oct-description {
            text-align: center;
            color: #666;
            margin-bottom: 25px;
            line-height: 1.5;
        }

        .oct-form-group {
            margin-bottom: 20px;
        }

        .oct-form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
        }

        .oct-input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #ddd;
            border-radius: 6px;
            font-size: 16px;
            transition: border-color 0.3s ease;
            box-sizing: border-box;
        }

        .oct-input:focus {
            outline: none;
            border-color: #2196f3;
            box-shadow: 0 0 0 3px rgba(33, 150, 243, 0.1);
        }

        .oct-submit-btn {
            width: 100%;
            padding: 12px 20px;
            background: linear-gradient(135deg, #aa5bf9, #3e48e1);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            position: relative;
        }

        .oct-submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }

        .oct-submit-btn:disabled {
            opacity: 0.7;
            cursor: not-allowed;
            transform: none;
        }

        .oct-loading {
            position: absolute;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
        }

        .oct-message {
            padding: 15px;
            border-radius: 6px;
            margin-top: 15px;
            text-align: center;
            font-weight: 500;
        }

        .oct-message.success {
            background-color: #e8f5e9;
            color: #2e7d32;
            border-left: 4px solid #4caf50;
        }

        .oct-message.error {
            background-color: #ffebee;
            color: #c62828;
            border-left: 4px solid #f44336;
        }

        .oct-email-error, .oct-captcha-error {
            color: #c62828;
            font-size: 14px;
            margin-top: 5px;
        }

        .oct-privacy-note {
            margin-top: 20px;
            padding: 15px;
            background-color: #f5f5f5;
            border-radius: 6px;
            text-align: center;
        }

        .h-captcha {
            margin: 15px 0;
        }

        @media (max-width: 600px) {
            .oct-form-wrapper {
                margin: 10px;
                padding: 20px;
            }
        }
        </style>

        <script>
        jQuery(document).ready(function($) {
            $('#opencitations-token-form').on('submit', function(e) {
                e.preventDefault();

                // Reset previous errors
                $('.oct-email-error, .oct-captcha-error').hide();
                $('#oct-message').hide();

                const email = $('#oct-email').val().trim();
                const hcaptchaResponse = hcaptcha.getResponse();

                // Email validation
                if (!email || !isValidEmail(email)) {
                    $('.oct-email-error').text('Please enter a valid email address.').show();
                    return;
                }

                // hCaptcha validation
                if (!hcaptchaResponse) {
                    $('.oct-captcha-error').text('Please complete the captcha verification.').show();
                    return;
                }

                // Disable form and show loading
                $('#oct-submit-btn').prop('disabled', true);
                $('.oct-btn-text').hide();
                $('.oct-loading').show();

                // AJAX request
                $.ajax({
                    url: oct_ajax.ajax_url,
                    type: 'POST',
                    data: {
                        action: 'request_opencitations_token',
                        email: email,
                        'h-captcha-response': hcaptchaResponse,
                        nonce: oct_ajax.nonce
                    },
                    success: function(response) {
                        if (response.success) {
                            showMessage('success', response.data.message);
                            $('#opencitations-token-form')[0].reset();
                            hcaptcha.reset();
                        } else {
                            showMessage('error', response.data.message || 'An error occurred. Please try again.');
                        }
                    },
                    error: function() {
                        showMessage('error', 'Connection error. Please try again.');
                    },
                    complete: function() {
                        // Re-enable form
                        $('#oct-submit-btn').prop('disabled', false);
                        $('.oct-btn-text').show();
                        $('.oct-loading').hide();
                    }
                });
            });

            function showMessage(type, message) {
                $('#oct-message')
                    .removeClass('success error')
                    .addClass(type)
                    .text(message)
                    .show();
            }

            function isValidEmail(email) {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                return emailRegex.test(email);
            }
        });
        </script>
        <?php

        return ob_get_clean();
    }

    public function handle_token_request() {
        // Verify nonce
        if (!wp_verify_nonce($_POST['nonce'], 'oct_nonce')) {
            error_log('OpenCitations Token: Nonce verification failed');
            wp_send_json_error(array('message' => 'Security check failed'));
            return;
        }

        $email = sanitize_email($_POST['email']);
        $hcaptcha_response = sanitize_text_field($_POST['h-captcha-response']);

        error_log('OpenCitations Token: Processing request for email: ' . $email);

        // Email validation
        if (!is_email($email)) {
            error_log('OpenCitations Token: Invalid email format: ' . $email);
            wp_send_json_error(array('message' => 'Invalid email address.'));
            return;
        }

        // Verify hCaptcha
        if (!$this->verify_hcaptcha($hcaptcha_response)) {
            error_log('OpenCitations Token: hCaptcha verification failed for: ' . $email);
            wp_send_json_error(array('message' => 'Captcha verification failed. Please try again.'));
            return;
        }

        error_log('OpenCitations Token: hCaptcha verified, generating token...');

        // Generate and store token
        $result = $this->generate_and_store_token($email);

        if ($result['success']) {
            error_log('OpenCitations Token: Token generated successfully: ' . $result['token']);

            // Send email
            $email_sent = $this->send_token_email($email, $result['token']);

            if ($email_sent) {
                error_log('OpenCitations Token: Email sent successfully to: ' . $email);
                wp_send_json_success(array(
                    'message' => 'Token generated successfully! You will receive your access token via email shortly.'
                ));
            } else {
                error_log('OpenCitations Token: Email sending failed for: ' . $email);
                wp_send_json_success(array(
                    'message' => 'Token generated successfully! Your token is: ' . $result['token'] . ' (Email delivery failed - please contact support if needed)'
                ));
            }
        } else {
            error_log('OpenCitations Token: Token generation failed: ' . $result['message']);
            wp_send_json_error(array(
                'message' => $result['message'] ?: 'Failed to generate token. Please try again later.'
            ));
        }
    }

    private function verify_hcaptcha($response) {
        if (empty($this->hcaptcha_secret_key) || empty($response)) {
            return false;
        }

        $verify_url = 'https://hcaptcha.com/siteverify';
        $data = array(
            'secret' => $this->hcaptcha_secret_key,
            'response' => $response,
            'remoteip' => $_SERVER['REMOTE_ADDR']
        );

        $options = array(
            'http' => array(
                'header' => "Content-type: application/x-www-form-urlencoded\r\n",
                'method' => 'POST',
                'content' => http_build_query($data)
            )
        );

        $context = stream_context_create($options);
        $result = file_get_contents($verify_url, false, $context);
        $response_data = json_decode($result, true);

        return isset($response_data['success']) && $response_data['success'] === true;
    }

    private function generate_and_store_token($email) {
        // Check if Redis extension is loaded
        if (!extension_loaded('redis')) {
            error_log('OpenCitations Token: Redis PHP extension not loaded');
            return array('success' => false, 'message' => 'Redis extension not available. Please try again in a few minutes.');
        }

        try {
            // Connect to Redis
            $redis = new Redis();
            $connected = $redis->connect($this->redis_host, $this->redis_port, 10);

            if (!$connected) {
                error_log('OpenCitations Token: Failed to connect to Redis');
                return array('success' => false, 'message' => 'Database connection failed');
            }

            // Authenticate if password is set
            if (!empty($this->redis_password)) {
                $auth = $redis->auth($this->redis_password);
                if (!$auth) {
                    error_log('OpenCitations Token: Redis authentication failed');
                    $redis->close();
                    return array('success' => false, 'message' => 'Database authentication failed');
                }
            }

            // Check for rate limiting (email cooldown)
            $email_key = 'opencitations:email:' . md5($email);
            if ($redis->exists($email_key)) {
                $redis->close();
                return array('success' => false, 'message' => 'Please wait 5 minutes before requesting another token for this email address.');
            }

            // Generate unique token
            $token = $this->generate_unique_token($redis);

            // Store ONLY the token in Redis as string (no timestamp or personal data)
            $stored = $redis->set($token, $token);

            // Store email hash for cooldown only (temporary, 5 minutes)
            $redis->setex($email_key, 300, $token);

            $redis->close();

            if ($stored) {
                error_log('OpenCitations Token: Token generated successfully for email: ' . $email);
                return array('success' => true, 'token' => $token);
            } else {
                error_log('OpenCitations Token: Failed to store token in Redis');
                return array('success' => false, 'message' => 'Failed to store token');
            }

        } catch (Exception $e) {
            error_log('OpenCitations Token: Redis error: ' . $e->getMessage());
            return array('success' => false, 'message' => 'Database error occurred. Please try again in a few minutes.');
        }
    }

    private function generate_unique_token($redis) {
        $max_attempts = 10;
        $attempts = 0;

        do {
            // Generate UUID token + epoch time for extra entropy
            $uuid = wp_generate_uuid4();
            $epoch_time = time();
            $token = $uuid . '-' . $epoch_time;
            $attempts++;

            // Check if token already exists
            $exists = $redis->exists($token);

        } while ($exists && $attempts < $max_attempts);

        if ($attempts >= $max_attempts) {
            // Fallback to timestamp-based UUID + epoch if collision issues
            $uuid = sprintf('%08x-%04x-%04x-%04x-%012x',
                time(),
                mt_rand(0, 0xffff),
                mt_rand(0, 0x0fff) | 0x4000,
                mt_rand(0, 0x3fff) | 0x8000,
                mt_rand(0, 0xffffffffffff)
            );
            $token = $uuid . '-' . time();
        }

        return $token;
    }

    private function send_token_email($email, $token) {
        // Configure SMTP if settings are provided
        if (!empty($this->smtp_host) && !empty($this->smtp_user)) {
            add_action('phpmailer_init', array($this, 'configure_smtp'));
        }

        $subject = 'Your OpenCitations Access Token';

        // Create HTML email content
        $html_content = '
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your OpenCitations Access Token</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #aa5bf9, #3e48e1); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }
        .header h1 { margin: 0; font-size: 24px; font-weight: normal; }
        .content { background: #ffffff; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #ddd; }
        .token-box { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; padding: 20px; margin: 20px 0; text-align: center; }
        .token { font-family: Consolas, "Courier New", monospace; font-size: 16px; font-weight: bold; color: #333; word-break: break-all; background: #e9ecef; padding: 10px; border-radius: 4px; }
        .code-block { background: #f8f9fa; color: #333; padding: 15px; border-radius: 6px; margin: 15px 0; font-family: Consolas, "Courier New", monospace; font-size: 14px; overflow-x: auto; border: 1px solid #dee2e6; white-space: pre-wrap; word-wrap: break-word; }
        .highlight { background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0; border-radius: 4px; }
        .footer { text-align: left; margin-top: 30px; padding: 20px 0; color: #666; font-size: 14px; border-top: 1px solid #eee; }
        ul { padding-left: 20px; }
        li { margin: 8px 0; }
        h3 { color: #333; margin-top: 25px; }
    </style>
</head>
<body>
    <h4>***If you weren\'t expecting this email or didn\'t sign up for it, feel free to delete it and take no further action.***</h4>

    <div class="header">
        <h1>Your OpenCitations Access Token</h1>
    </div>

    <div class="content">
        <p>Hello,</p>

        <p>Thank you for requesting an OpenCitations access token.</p>

        <div class="token-box">
            <strong>Your personal access token is:</strong><br><br>
            <div class="token">' . esc_html($token) . '</div>
        </div>

        <div class="highlight">
            <strong>IMPORTANT:</strong> This token is PERMANENT and should be saved securely. Please reuse this same token for all your future OpenCitations API requests.
        </div>

        <h3>How to use your token:</h3>
        <p>When making API calls to OpenCitations, include this token in the authorization header:</p>

        <strong>Example in Python:</strong>
        <div class="code-block">import requests<br>
    headers = {&quot;authorization&quot;: &quot;' . esc_html($token) . '&quot;}<br>
    response = requests.get(&quot;https://api.opencitations.net/meta/v1/metadata/doi:10.1162/qss_a_00023&quot;, headers=headers)
        </div>

        <strong>Example in curl:</strong>
        <div class="code-block">curl -H &quot;authorization: ' . esc_html($token) . '&quot; &quot;https://api.opencitations.net/meta/v1/metadata/doi:10.1162/qss_a_00023&quot;</div>

        <h3>Privacy and Usage:</h3>
        <ul>
            <li>This token NEVER EXPIRES - save it securely and reuse it</li>
            <li>Your email address is NOT stored permanently in our system</li>
            <li>The token allows anonymous usage monitoring without personal data</li>
            <li>Using your token helps demonstrate OpenCitations impact in research</li>
        </ul>

        <div class="footer">
            <p>Best regards,<br>The OpenCitations Team</p>
        </div>
    </div>
</body>
</html>';

        $headers = array(
            'Content-Type: text/html; charset=UTF-8',
            'From: ' . $this->from_name . ' <' . $this->from_email . '>'
        );

        $sent = wp_mail($email, $subject, $html_content, $headers);

        // Remove SMTP configuration after sending
        if (!empty($this->smtp_host) && !empty($this->smtp_user)) {
            remove_action('phpmailer_init', array($this, 'configure_smtp'));
        }

        if ($sent) {
            error_log('OpenCitations Token: Email sent successfully to: ' . $email);
        } else {
            error_log('OpenCitations Token: Failed to send email to: ' . $email);
        }

        return $sent;
    }

    public function configure_smtp($phpmailer) {
        $phpmailer->isSMTP();
        $phpmailer->Host = $this->smtp_host;
        $phpmailer->SMTPAuth = true;
        $phpmailer->Port = $this->smtp_port;
        $phpmailer->Username = $this->smtp_user;
        $phpmailer->Password = $this->smtp_password;

        if ($this->smtp_secure === 'ssl') {
            $phpmailer->SMTPSecure = 'ssl';
        } elseif ($this->smtp_secure === 'tls') {
            $phpmailer->SMTPSecure = 'tls';
        }

        $phpmailer->From = $this->from_email;
        $phpmailer->FromName = $this->from_name;
    }

    // NEW: Function to collect all tokens from Redis
    private function collect_all_tokens() {
        if (!extension_loaded('redis')) {
            return array('success' => false, 'message' => 'Redis extension not available');
        }

        try {
            $redis = new Redis();
            $connected = $redis->connect($this->redis_host, $this->redis_port, 10);

            if (!$connected) {
                return array('success' => false, 'message' => 'Redis connection failed');
            }

            // Authenticate if password is set
            if (!empty($this->redis_password)) {
                $auth = $redis->auth($this->redis_password);
                if (!$auth) {
                    $redis->close();
                    return array('success' => false, 'message' => 'Redis authentication failed');
                }
            }

            // Get all keys
            $all_keys = $redis->keys('*');
            $token_keys = array();

            // Filter keys that match token patterns (exclude email cooldown keys)
            foreach ($all_keys as $key) {
                // Skip email cooldown keys
                if (strpos($key, 'opencitations:email:') !== false) {
                    continue;
                }
                
                $hyphen_count = substr_count($key, '-');
                
                // Old tokens: exactly 4 hyphens (UUID format)
                // New tokens: exactly 5 hyphens (UUID-EPOCH format)
                if ($hyphen_count == 4 || $hyphen_count == 5) {
                    // Additional check: should be UUID-like (no spaces, reasonable length)
                    if (strlen($key) >= 36 && strlen($key) <= 60 && !preg_match('/\s/', $key)) {
                        $token_keys[] = $key;
                    }
                }
            }

            $redis->close();

            // Sort tokens by creation date (newer first)
            usort($token_keys, function($a, $b) {
                // Extract creation time from new format tokens
                $time_a = $this->extract_token_time($a);
                $time_b = $this->extract_token_time($b);
                
                // If both have times, sort by time (newer first)
                if ($time_a && $time_b) {
                    return $time_b - $time_a;
                }
                
                // Put tokens with times before those without
                if ($time_a && !$time_b) return -1;
                if (!$time_a && $time_b) return 1;
                
                // For tokens without times, sort alphabetically
                return strcmp($a, $b);
            });

            return array('success' => true, 'tokens' => $token_keys);

        } catch (Exception $e) {
            error_log('OpenCitations Token: Error collecting tokens: ' . $e->getMessage());
            return array('success' => false, 'message' => 'Error collecting tokens: ' . $e->getMessage());
        }
    }

    // NEW: Helper function to extract creation time from token
    private function extract_token_time($token) {
        $hyphen_count = substr_count($token, '-');
        
        // Only new format tokens (5 hyphens) have timestamps
        if ($hyphen_count == 5) {
            $parts = explode('-', $token);
            $epoch_time = end($parts);
            if (is_numeric($epoch_time) && $epoch_time > 1000000000) {
                return (int)$epoch_time;
            }
        }
        
        return null;
    }

    // NEW: Function to create backup file content
    private function create_backup_content($tokens) {
        $content = "OpenCitations Token Backup\n";
        $content .= "Generated on: " . date('Y-m-d H:i:s') . " UTC\n";
        $content .= "Total tokens: " . count($tokens) . "\n";
        $content .= str_repeat("=", 50) . "\n\n";

        $old_tokens = 0;
        $new_tokens = 0;

        foreach ($tokens as $token) {
            $creation_time = $this->extract_token_time($token);
            
            if ($creation_time) {
                $content .= $token . " (Created: " . date('Y-m-d H:i:s', $creation_time) . ")\n";
                $new_tokens++;
            } else {
                $content .= $token . " (Legacy token)\n";
                $old_tokens++;
            }
        }

        $content .= "\n" . str_repeat("=", 50) . "\n";
        $content .= "Summary:\n";
        $content .= "Legacy tokens (UUID only): " . $old_tokens . "\n";
        $content .= "New tokens (UUID-EPOCH): " . $new_tokens . "\n";
        $content .= "Total: " . count($tokens) . "\n";

        return $content;
    }

    // NEW: Function to send backup email with attachment
    private function send_backup_email($backup_emails, $tokens) {
        if (empty($backup_emails) || empty($tokens)) {
            return false;
        }

        // Parse email addresses
        $email_list = array_map('trim', explode(',', $backup_emails));
        $email_list = array_filter($email_list, 'is_email');

        if (empty($email_list)) {
            error_log('OpenCitations Token: No valid backup email addresses found');
            return false;
        }

        // Configure SMTP if settings are provided
        if (!empty($this->smtp_host) && !empty($this->smtp_user)) {
            add_action('phpmailer_init', array($this, 'configure_smtp'));
        }

        $filename = 'opencitations_tokens_backup_' . date('Y-m-d_H-i-s') . '.txt';
        $backup_content = $this->create_backup_content($tokens);

        // Create temporary file
        $temp_file = wp_upload_dir()['basedir'] . '/' . $filename;
        file_put_contents($temp_file, $backup_content);

        $subject = 'OpenCitations Token Backup - ' . date('Y-m-d');
        
        $html_content = '
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #aa5bf9, #3e48e1); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }
        .content { background: #ffffff; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #ddd; }
        .stats { background: #f8f9fa; padding: 15px; border-radius: 6px; margin: 20px 0; }
        .footer { text-align: center; margin-top: 30px; padding: 15px; color: #666; font-size: 14px; border-top: 1px solid #eee; }
    </style>
</head>
<body>
    <div class="header">
        <h1>OpenCitations Token Backup</h1>
    </div>

    <div class="content">
        <p>Hello,</p>

        <p>This is your scheduled backup of all OpenCitations tokens.</p>

        <div class="stats">
            <strong>Backup Statistics:</strong><br>
            <ul>
                <li>Backup Date: ' . date('Y-m-d H:i:s') . ' UTC</li>
                <li>Total Tokens: ' . count($tokens) . '</li>
                <li>File: ' . $filename . '</li>
            </ul>
        </div>

        <p>The complete list of tokens is attached to this email as a text file.</p>

        <div class="footer">
            <p>Best regards,<br>OpenCitations Token Management System</p>
        </div>
    </div>
</body>
</html>';

        $headers = array(
            'Content-Type: text/html; charset=UTF-8',
            'From: ' . $this->from_name . ' <' . $this->from_email . '>'
        );

        $sent = false;
        foreach ($email_list as $email) {
            $individual_sent = wp_mail($email, $subject, $html_content, $headers, array($temp_file));
            if ($individual_sent) {
                $sent = true;
                error_log('OpenCitations Token: Backup email sent successfully to: ' . $email);
            } else {
                error_log('OpenCitations Token: Failed to send backup email to: ' . $email);
            }
        }

        // Clean up temporary file
        if (file_exists($temp_file)) {
            unlink($temp_file);
        }

        // Remove SMTP configuration after sending
        if (!empty($this->smtp_host) && !empty($this->smtp_user)) {
            remove_action('phpmailer_init', array($this, 'configure_smtp'));
        }

        return $sent;
    }

    // NEW: Monthly backup function (called by cron)
    public function send_monthly_backup() {
        error_log('OpenCitations Token: Starting monthly backup');

        $backup_emails = get_option('oct_backup_emails', '');
        if (empty($backup_emails)) {
            error_log('OpenCitations Token: No backup emails configured, skipping monthly backup');
            return;
        }

        $result = $this->collect_all_tokens();
        if (!$result['success']) {
            error_log('OpenCitations Token: Failed to collect tokens for monthly backup: ' . $result['message']);
            return;
        }

        $backup_sent = $this->send_backup_email($backup_emails, $result['tokens']);
        if ($backup_sent) {
            error_log('OpenCitations Token: Monthly backup sent successfully');
        } else {
            error_log('OpenCitations Token: Failed to send monthly backup');
        }
    }

    // Admin page
    public function add_admin_menu() {
        add_options_page(
            'OpenCitations Token Settings',
            'OpenCitations Token',
            'manage_options',
            'opencitations-token',
            array($this, 'admin_page')
        );
    }

    public function admin_page() {
        if (isset($_POST['submit'])) {
            update_option('oct_hcaptcha_site_key', sanitize_text_field($_POST['hcaptcha_site_key']));
            update_option('oct_hcaptcha_secret_key', sanitize_text_field($_POST['hcaptcha_secret_key']));
            update_option('oct_redis_host', sanitize_text_field($_POST['redis_host']));
            update_option('oct_redis_port', intval($_POST['redis_port']) ?: 6379);
            update_option('oct_redis_password', sanitize_text_field($_POST['redis_password']));
            update_option('oct_from_email', sanitize_email($_POST['from_email']));
            update_option('oct_from_name', sanitize_text_field($_POST['from_name']));
            update_option('oct_smtp_host', sanitize_text_field($_POST['smtp_host']));
            update_option('oct_smtp_port', intval($_POST['smtp_port']) ?: 587);
            update_option('oct_smtp_user', sanitize_text_field($_POST['smtp_user']));
            update_option('oct_smtp_password', sanitize_text_field($_POST['smtp_password']));
            update_option('oct_smtp_secure', sanitize_text_field($_POST['smtp_secure']));
            update_option('oct_backup_emails', sanitize_textarea_field($_POST['backup_emails'])); // NEW

            echo '<div class="notice notice-success"><p>Settings saved!</p></div>';

            // Reload configuration
            $this->load_config();
        }

        // NEW: Handle manual backup send
        if (isset($_POST['send_backup_now'])) {
            if (empty($this->backup_emails)) {
                echo '<div class="notice notice-error"><p>Please configure backup email addresses first.</p></div>';
            } else {
                $result = $this->collect_all_tokens();
                if ($result['success']) {
                    $backup_sent = $this->send_backup_email($this->backup_emails, $result['tokens']);
                    if ($backup_sent) {
                        echo '<div class="notice notice-success"><p>Backup sent successfully to configured email addresses!</p></div>';
                    } else {
                        echo '<div class="notice notice-error"><p>Failed to send backup. Please check your email configuration.</p></div>';
                    }
                } else {
                    echo '<div class="notice notice-error"><p>Failed to collect tokens: ' . esc_html($result['message']) . '</p></div>';
                }
            }
        }
        ?>
        <div class="wrap">
            <h1>OpenCitations Token Settings</h1>
            <form method="post" action="">
                <h2>hCaptcha Configuration</h2>
                <table class="form-table">
                    <tr>
                        <th scope="row">hCaptcha Site Key</th>
                        <td>
                            <input type="text" name="hcaptcha_site_key" value="<?php echo esc_attr($this->hcaptcha_site_key); ?>" class="regular-text" />
                            <p class="description">Get your keys from <a href="https://hcaptcha.com" target="_blank">hcaptcha.com</a></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">hCaptcha Secret Key</th>
                        <td>
                            <input type="password" name="hcaptcha_secret_key" value="<?php echo esc_attr($this->hcaptcha_secret_key); ?>" class="regular-text" />
                        </td>
                    </tr>
                </table>

                <h2>Redis Configuration</h2>
                <table class="form-table">
                    <tr>
                        <th scope="row">Redis Host</th>
                        <td>
                            <input type="text" name="redis_host" value="<?php echo esc_attr($this->redis_host); ?>" class="regular-text" placeholder="redis-service.default.svc.cluster.local" />
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">Redis Port</th>
                        <td>
                            <input type="number" name="redis_port" value="<?php echo esc_attr($this->redis_port); ?>" class="small-text" placeholder="6379" />
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">Redis Password</th>
                        <td>
                            <input type="password" name="redis_password" value="<?php echo esc_attr($this->redis_password); ?>" class="regular-text" placeholder="Leave empty if no password" />
                        </td>
                    </tr>
                </table>

                <h2>Email Configuration</h2>
                <table class="form-table">
                    <tr>
                        <th scope="row">From Email</th>
                        <td>
                            <input type="email" name="from_email" value="<?php echo esc_attr($this->from_email); ?>" class="regular-text" />
                            <p class="description">Email address used as sender for token emails</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">From Name</th>
                        <td>
                            <input type="text" name="from_name" value="<?php echo esc_attr($this->from_name); ?>" class="regular-text" />
                            <p class="description">Name used as sender for token emails</p>
                        </td>
                    </tr>
                </table>

                <!-- NEW: Backup Email Configuration -->
                <h2>Backup Configuration</h2>
                <table class="form-table">
                    <tr>
                        <th scope="row">Backup Email Addresses</th>
                        <td>
                            <textarea name="backup_emails" rows="4" class="large-text" placeholder="admin@example.com, backup@example.com"><?php echo esc_textarea($this->backup_emails); ?></textarea>
                            <p class="description">Comma-separated list of email addresses to receive monthly token backups. These emails will receive a text file with all active tokens.</p>
                        </td>
                    </tr>
                </table>

                <h2>SMTP Configuration</h2>
                <p>Configure SMTP settings for reliable email delivery. Leave empty to use default WordPress mail.</p>
                <table class="form-table">
                    <tr>
                        <th scope="row">SMTP Host</th>
                        <td>
                            <input type="text" name="smtp_host" value="<?php echo esc_attr($this->smtp_host); ?>" class="regular-text" placeholder="smtp.gmail.com" />
                            <p class="description">SMTP server hostname</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">SMTP Port</th>
                        <td>
                            <input type="number" name="smtp_port" value="<?php echo esc_attr($this->smtp_port); ?>" class="small-text" placeholder="587" />
                            <p class="description">Usually 587 for TLS or 465 for SSL</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">SMTP Username</th>
                        <td>
                            <input type="text" name="smtp_user" value="<?php echo esc_attr($this->smtp_user); ?>" class="regular-text" placeholder="your.email@gmail.com" />
                            <p class="description">SMTP authentication username</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">SMTP Password</th>
                        <td>
                            <input type="password" name="smtp_password" value="<?php echo esc_attr($this->smtp_password); ?>" class="regular-text" />
                            <p class="description">SMTP authentication password</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row">SMTP Security</th>
                        <td>
                            <select name="smtp_secure">
                                <option value="tls" <?php selected($this->smtp_secure, 'tls'); ?>>TLS</option>
                                <option value="ssl" <?php selected($this->smtp_secure, 'ssl'); ?>>SSL</option>
                                <option value="none" <?php selected($this->smtp_secure, 'none'); ?>>None</option>
                            </select>
                            <p class="description">Encryption method (TLS recommended)</p>
                        </td>
                    </tr>
                </table>

                <?php submit_button(); ?>
            </form>

            <!-- NEW: Manual backup section -->
            <h2>Token Backup Management</h2>
            <p>Backups are automatically sent on the first day of each month. You can also send a backup immediately using the button below.</p>
            
            <form method="post" style="margin-bottom: 20px;">
                <input type="hidden" name="send_backup_now" value="1">
                <button type="submit" class="button button-primary" style="background: #28a745; border-color: #28a745;">
                    📤 Send Backup Now
                </button>
                <p class="description">This will immediately send a backup file with all current tokens to the configured backup email addresses.</p>
            </form>

            <?php
            // Show next scheduled backup
            $next_backup = wp_next_scheduled('opencitations_monthly_backup');
            if ($next_backup) {
                echo '<p><strong>Next scheduled backup:</strong> ' . date('Y-m-d H:i:s', $next_backup) . ' UTC</p>';
            } else {
                echo '<p><strong>Monthly backup:</strong> Not scheduled (will be scheduled on plugin activation)</p>';
            }
            ?>

            <h2>Usage</h2>
            <p>Use the shortcode <code>[opencitations_token_form]</code> to display the form on any page or post.</p>

            <h2>Token Management</h2>
            <p>Tokens are stored permanently in Redis for anonymous usage tracking:</p>
            <ul>
                <li><strong>Old Format (Legacy):</strong> UUID only - <code>8e90974a-cc1f-486b-a479-5f3779b094f2</code></li>
                <li><strong>New Format:</strong> UUID-EPOCHTIME - <code>457ce675-afbd-47c5-9218-192bbc9d024f-1748350084</code></li>
                <li><strong>Key:</strong> TOKEN_VALUE (no prefix)</li>
                <li><strong>Value:</strong> The token itself</li>
                <li><strong>Expiration:</strong> <strong>PERMANENT</strong> (tokens never expire)</li>
                <li><strong>Purpose:</strong> Anonymous identification for API usage monitoring</li>
            </ul>

            <h3>Rate Limiting</h3>
            <ul>
                <li><strong>Email cooldown:</strong> 5 minutes between token requests per email</li>
                <li><strong>Storage:</strong> <code>opencitations:email:md5hash</code> (temporary, 5 min TTL)</li>
                <li><strong>Purpose:</strong> Prevent spam and duplicate token requests</li>
            </ul>

            <h3>Privacy & Analytics</h3>
            <p>Maximum privacy approach:</p>
            <ul>
                <li><strong>No personal data</strong> stored permanently in Redis</li>
                <li><strong>Only token as key and value</strong> for creation date analytics</li>
                <li><strong>Anonymous identification</strong> for API usage patterns</li>
                <li><strong>Email hashes</strong> used only for rate limiting (temporary)</li>
            </ul>

            <!-- NEW: Backup Information -->
            <h3>Backup System</h3>
            <p>Automated backup features:</p>
            <ul>
                <li><strong>Monthly Schedule:</strong> Backups are sent automatically on the first day of each month</li>
                <li><strong>File Format:</strong> Plain text file with tokens and creation dates</li>
                <li><strong>Security:</strong> Backup emails should be sent to secure, monitored addresses</li>
                <li><strong>Manual Backup:</strong> Use "Send Backup Now" button for immediate backup</li>
            </ul>

            <h3>Test Redis Connection</h3>
            <?php if (isset($_POST['test_redis'])): ?>
            <div class="notice notice-info">
                <?php
                if (!extension_loaded('redis')) {
                    echo '<p><strong>❌ Redis PHP extension not loaded</strong></p>';
                    echo '<p>Please wait for the container to finish installing the Redis extension, then try again.</p>';
                } else {
                    try {
                        $redis = new Redis();
                        $connected = $redis->connect($this->redis_host, $this->redis_port, 5);
                        if ($connected) {
                            $auth_success = true;
                            if (!empty($this->redis_password)) {
                                $auth_success = $redis->auth($this->redis_password);
                            }

                            if ($auth_success) {
                                echo '<p><strong>✅ Redis connection successful!</strong></p>';
                                $info = $redis->info('server');
                                echo '<p>Redis version: ' . esc_html($info['redis_version']) . '</p>';
                                echo '<p>Redis mode: ' . esc_html($info['redis_mode']) . '</p>';

                                // Test write/read
                                $test_key = 'opencitations:test:' . time();
                                $redis->setex($test_key, 10, 'test_value');
                                $test_value = $redis->get($test_key);
                                $redis->del($test_key);

                                if ($test_value === 'test_value') {
                                    echo '<p>✅ Read/Write test: <strong>Passed</strong></p>';
                                } else {
                                    echo '<p>⚠️ Read/Write test: <strong>Failed</strong></p>';
                                }
                            } else {
                                echo '<p><strong>❌ Redis authentication failed</strong></p>';
                                echo '<p>Check your Redis password configuration.</p>';
                            }
                            $redis->close();
                        } else {
                            echo '<p><strong>❌ Redis connection failed</strong></p>';
                            echo '<p>Check host and port configuration.</p>';
                        }
                    } catch (Exception $e) {
                        echo '<p><strong>❌ Redis error:</strong> ' . esc_html($e->getMessage()) . '</p>';
                    }
                }
                ?>
            </div>
            <?php endif; ?>

            <form method="post" style="margin-top: 10px;">
                <input type="hidden" name="test_redis" value="1">
                <button type="submit" class="button">Test Redis Connection</button>
                <input type="hidden" name="show_stats" value="1">
                <button type="submit" name="show_stats" class="button" style="margin-left: 10px;">Show Token Statistics</button>
                <button type="submit" name="test_email" class="button" style="margin-left: 10px;">Send Test Email</button>
                <button type="submit" name="debug_tokens" class="button" style="margin-left: 10px; background: #ff6b6b; color: white;">Debug Tokens</button>
            </form>

            <?php if (isset($_POST['test_email'])): ?>
            <h3>Email Test Result</h3>
            <div class="notice notice-info">
                <?php
                $test_result = $this->send_token_email($this->from_email, 'TEST12345');
                if ($test_result) {
                    echo '<p><strong>✅ Test email sent successfully!</strong></p>';
                    echo '<p>Check your inbox at: ' . esc_html($this->from_email) . '</p>';
                } else {
                    echo '<p><strong>❌ Test email failed to send</strong></p>';
                    echo '<p>Check your SMTP configuration and try again.</p>';
                }
                ?>
            </div>
            <?php endif; ?>

            <?php if (isset($_POST['debug_tokens']) && extension_loaded('redis')): ?>
            <h3>Debug - All Redis Keys</h3>
            <div class="notice notice-info">
                <?php
                try {
                    $redis = new Redis();
                    $connected = $redis->connect($this->redis_host, $this->redis_port, 5);
                    if ($connected && (empty($this->redis_password) || $redis->auth($this->redis_password))) {
                        
                        echo '<h4>Debug - All Redis Keys:</h4>';
                        echo '<pre style="background: #f9f9f9; padding: 15px; border-left: 4px solid #007cba; max-height: 400px; overflow-y: auto;">';
                        $all_keys = $redis->keys('*');
                        echo 'Total keys found: ' . count($all_keys) . "\n\n";
                        
                        foreach (array_slice($all_keys, 0, 30) as $key) { // primi 30
                            $value = $redis->get($key);
                            echo "Key: '" . $key . "' => Value: '" . $value . "'\n";
                            echo "Hyphens in key: " . substr_count($key, '-') . "\n";
                            echo "Key length: " . strlen($key) . "\n";
                            echo "Ends with number: " . (is_numeric(substr(strrchr($key, '-'), 1)) ? 'YES' : 'NO') . "\n";
                            echo "Contains 'opencitations:email:': " . (strpos($key, 'opencitations:email:') !== false ? 'YES' : 'NO') . "\n";
                            echo "---\n";
                        }
                        
                        if (count($all_keys) > 30) {
                            echo "\n... and " . (count($all_keys) - 30) . " more keys\n";
                        }
                        
                        echo '</pre>';
                        $redis->close();
                    } else {
                        echo '<p>❌ Cannot connect to Redis for debug</p>';
                    }
                } catch (Exception $e) {
                    echo '<p><strong>❌ Error during debug:</strong> ' . esc_html($e->getMessage()) . '</p>';
                }
                ?>
            </div>
            <?php endif; ?>

            <?php if (isset($_POST['show_stats']) && extension_loaded('redis')): ?>
            <h3>Token Statistics</h3>
            <div class="notice notice-info">
                <?php
                try {
                    $redis = new Redis();
                    $connected = $redis->connect($this->redis_host, $this->redis_port, 5);
                    if ($connected && (empty($this->redis_password) || $redis->auth($this->redis_password))) {

                        // Get all keys
                        $all_keys = $redis->keys('*');
                        $token_keys = array();

                        // Filter keys that match both old and new token patterns
                        foreach ($all_keys as $key) {
                            // Skip email cooldown keys
                            if (strpos($key, 'opencitations:email:') !== false) {
                                continue;
                            }
                            
                            $hyphen_count = substr_count($key, '-');
                            
                            // Old tokens: exactly 4 hyphens (UUID format)
                            // New tokens: exactly 5 hyphens (UUID-EPOCH format)
                            if ($hyphen_count == 4 || $hyphen_count == 5) {
                                // Additional check: should be UUID-like (no spaces, reasonable length)
                                if (strlen($key) >= 36 && strlen($key) <= 60 && !preg_match('/\s/', $key)) {
                                    $token_keys[] = $key;
                                }
                            }
                        }

                        $total_tokens = count($token_keys);
                        
                        // Count old vs new tokens
                        $old_tokens = 0;
                        $new_tokens = 0;
                        
                        foreach ($token_keys as $token_key) {
                            if (substr_count($token_key, '-') == 4) {
                                $old_tokens++;
                            } else {
                                $new_tokens++;
                            }
                        }

                        echo '<p><strong>Total Active Tokens:</strong> ' . $total_tokens . '</p>';
                        echo '<p><strong>Legacy Tokens (UUID only):</strong> ' . $old_tokens . '</p>';
                        echo '<p><strong>New Tokens (UUID-EPOCH):</strong> ' . $new_tokens . '</p>';

                        if ($total_tokens > 0) {
                            // Get creation dates from recent tokens
                            $recent_tokens = array_slice($token_keys, -50); // Last 50 tokens
                            $creation_dates = array();

                            foreach ($recent_tokens as $token_key) {
                                $token_value = $redis->get($token_key);
                                if ($token_value) {
                                    // Check if it's old format (UUID only) or new format (UUID-EPOCH)
                                    $hyphen_count = substr_count($token_value, '-');
                                    
                                    if ($hyphen_count == 5) {
                                        // New format: extract epoch time
                                        $parts = explode('-', $token_value);
                                        $epoch_time = end($parts);
                                        if (is_numeric($epoch_time) && $epoch_time > 1000000000) {
                                            $creation_dates[] = date('Y-m-d', $epoch_time);
                                        }
                                    } else {
                                        // Old format: no creation date available
                                        $creation_dates[] = 'Legacy (no date)';
                                    }
                                }
                            }

                            if (!empty($creation_dates)) {
                                $date_counts = array_count_values($creation_dates);
                                arsort($date_counts); // Sort by count descending

                                echo '<p><strong>Recent Activity (last 50 tokens):</strong></p>';
                                echo '<ul>';
                                $total_recent = 0;
                                foreach ($date_counts as $date => $count) {
                                    echo '<li>' . $date . ': ' . $count . ' tokens</li>';
                                    $total_recent += $count;
                                }
                                echo '</ul>';
                                echo '<p><em>Total recent tokens analyzed: ' . $total_recent . '</em></p>';
                            }
                        }

                        $redis->close();
                    } else {
                        echo '<p>❌ Cannot connect to Redis for statistics</p>';
                    }
                } catch (Exception $e) {
                    echo '<p><strong>❌ Error getting statistics:</strong> ' . esc_html($e->getMessage()) . '</p>';
                }
                ?>
            </div>
            <?php endif; ?>
        </div>
        <?php
    }
}

// Initialize plugin
new OpenCitationsTokenRequest();

// Activation hook
register_activation_hook(__FILE__, function() {
    // Set default values
    add_option('oct_redis_host', 'redis-service.default.svc.cluster.local');
    add_option('oct_redis_port', '6379');
    add_option('oct_from_email', get_option('admin_email'));
    add_option('oct_from_name', get_bloginfo('name'));
    add_option('oct_smtp_port', '587');
    add_option('oct_smtp_secure', 'tls');
    add_option('oct_backup_emails', ''); // NEW
    
    // Schedule monthly backup
    if (!wp_next_scheduled('opencitations_monthly_backup')) {
        wp_schedule_event(strtotime('first day of next month 00:00:00'), 'monthly', 'opencitations_monthly_backup');
    }
});

// Deactivation hook
register_deactivation_hook(__FILE__, function() {
    // Clean up scheduled events
    wp_clear_scheduled_hook('opencitations_monthly_backup');
});
?>
```
