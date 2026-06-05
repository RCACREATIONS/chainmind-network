<?php
/**
 * /api/node/register.php
 * ChainMind Node Registration Endpoint
 *
 * POST  /api/node/register.php
 * Body (JSON): { "email": "...", "password": "..." }
 *
 * Returns (JSON):
 *   Success: { "ok": true,  "node_secret": "...", "node_id": "...", "username": "..." }
 *   Error:   { "ok": false, "error": "..." }
 *
 * Database table required:
 * ─────────────────────────────────────────────────────────────
 *   CREATE TABLE users (
 *     id            INT AUTO_INCREMENT PRIMARY KEY,
 *     username      VARCHAR(64)  NOT NULL,
 *     email         VARCHAR(255) NOT NULL UNIQUE,
 *     password_hash VARCHAR(255) NOT NULL,
 *     created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
 *   );
 *
 *   CREATE TABLE node_registrations (
 *     id          INT AUTO_INCREMENT PRIMARY KEY,
 *     user_id     INT          NOT NULL,
 *     node_id     CHAR(36)     NOT NULL UNIQUE,
 *     node_secret CHAR(64)     NOT NULL UNIQUE,
 *     node_name   VARCHAR(128) DEFAULT '',
 *     created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
 *     last_seen   DATETIME     DEFAULT NULL,
 *     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
 *   );
 * ─────────────────────────────────────────────────────────────
 */

declare(strict_types=1);

// ── Config ───────────────────────────────────────────────────────────────────
// Update these values to match your database credentials.
define('DB_HOST', 'localhost');
define('DB_NAME', 'chainmind');       // your DB name
define('DB_USER', 'chainmind_user');  // your DB user
define('DB_PASS', 'your_db_password'); // your DB password
define('DB_CHARSET', 'utf8mb4');

// Rate limiting: max registrations per IP per minute
define('RATE_LIMIT',       5);
define('RATE_LIMIT_WINDOW', 60); // seconds

// ── Helpers ──────────────────────────────────────────────────────────────────

function json_response(array $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function get_db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $dsn = sprintf(
            'mysql:host=%s;dbname=%s;charset=%s',
            DB_HOST, DB_NAME, DB_CHARSET
        );
        $pdo = new PDO($dsn, DB_USER, DB_PASS, [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
    }
    return $pdo;
}

function generate_uuid(): string
{
    $data    = random_bytes(16);
    $data[6] = chr((ord($data[6]) & 0x0f) | 0x40);
    $data[8] = chr((ord($data[8]) & 0x3f) | 0x80);
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
}

function check_rate_limit(string $ip): void
{
    $db    = get_db();
    $since = date('Y-m-d H:i:s', time() - RATE_LIMIT_WINDOW);

    // Use a lightweight rate-limit table if you have one, or skip this block
    // if you handle rate limiting at the web-server (nginx/Apache) level.
    // Simple in-memory approach using a DB table:
    try {
        $db->exec("
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip         VARCHAR(45) NOT NULL,
                hits       INT         NOT NULL DEFAULT 1,
                window_start DATETIME  NOT NULL,
                PRIMARY KEY (ip)
            )
        ");
        $stmt = $db->prepare("
            INSERT INTO rate_limits (ip, hits, window_start)
            VALUES (:ip, 1, NOW())
            ON DUPLICATE KEY UPDATE
                hits = IF(window_start < :since, 1, hits + 1),
                window_start = IF(window_start < :since, NOW(), window_start)
        ");
        $stmt->execute([':ip' => $ip, ':since' => $since]);

        $row = $db->prepare("SELECT hits FROM rate_limits WHERE ip = :ip");
        $row->execute([':ip' => $ip]);
        $hits = (int)($row->fetchColumn() ?: 0);

        if ($hits > RATE_LIMIT) {
            json_response(['ok' => false, 'error' => 'Too many requests. Try again in a minute.'], 429);
        }
    } catch (PDOException $e) {
        // Rate-limit table may not exist in all setups — fail open
    }
}

// ── Main ─────────────────────────────────────────────────────────────────────

// Only allow POST
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_response(['ok' => false, 'error' => 'Method not allowed.'], 405);
}

// Parse JSON body
$body = json_decode(file_get_contents('php://input'), true);
if (!is_array($body)) {
    json_response(['ok' => false, 'error' => 'Invalid JSON body.'], 400);
}

$email    = trim((string)($body['email']    ?? ''));
$password = (string)($body['password'] ?? '');

if ($email === '' || $password === '') {
    json_response(['ok' => false, 'error' => 'email and password are required.'], 400);
}

if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    json_response(['ok' => false, 'error' => 'Invalid email address.'], 400);
}

// Rate limit by IP
$ip = $_SERVER['HTTP_X_FORWARDED_FOR'] ?? $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
$ip = explode(',', $ip)[0]; // take first IP if behind proxy
check_rate_limit($ip);

try {
    $db = get_db();

    // Look up user
    $stmt = $db->prepare('SELECT id, username, password_hash FROM users WHERE email = :email LIMIT 1');
    $stmt->execute([':email' => $email]);
    $user = $stmt->fetch();

    if (!$user || !password_verify($password, $user['password_hash'])) {
        // Same message for both "not found" and "wrong password" — avoids email enumeration
        json_response(['ok' => false, 'error' => 'Invalid email or password.'], 401);
    }

    $user_id  = (int)$user['id'];
    $username = (string)$user['username'];

    // Check if user already has a registration — reuse it so re-installs
    // don't create duplicate secrets.
    $stmt = $db->prepare('
        SELECT node_id, node_secret
        FROM node_registrations
        WHERE user_id = :uid
        ORDER BY created_at DESC
        LIMIT 1
    ');
    $stmt->execute([':uid' => $user_id]);
    $existing = $stmt->fetch();

    if ($existing) {
        $node_id     = $existing['node_id'];
        $node_secret = $existing['node_secret'];

        // Update last_seen
        $db->prepare('UPDATE node_registrations SET last_seen = NOW() WHERE node_id = :nid')
           ->execute([':nid' => $node_id]);
    } else {
        // Generate fresh credentials
        $node_id     = generate_uuid();
        $node_secret = bin2hex(random_bytes(32)); // 64-char hex

        $stmt = $db->prepare('
            INSERT INTO node_registrations (user_id, node_id, node_secret, last_seen)
            VALUES (:uid, :nid, :secret, NOW())
        ');
        $stmt->execute([
            ':uid'    => $user_id,
            ':nid'    => $node_id,
            ':secret' => $node_secret,
        ]);
    }

    json_response([
        'ok'          => true,
        'node_secret' => $node_secret,
        'node_id'     => $node_id,
        'username'    => $username,
    ]);

} catch (PDOException $e) {
    // Log full error server-side, return generic message to client
    error_log('ChainMind register.php DB error: ' . $e->getMessage());
    json_response(['ok' => false, 'error' => 'Server error. Please try again later.'], 500);
}
