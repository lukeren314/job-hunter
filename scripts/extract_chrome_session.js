#!/usr/bin/env node
/**
 * Extracts LinkedIn cookies from your existing Chrome session and saves them
 * in Playwright's storageState format to config/linkedin_session.json.
 *
 * This is an alternative to save_linkedin_session.js that works by reading
 * Chrome's on-disk cookie database (no new browser window needed).
 *
 * Prerequisites: Chrome must be installed; the script uses the macOS Keychain
 * to decrypt cookie values.
 *
 * Usage:
 *   node scripts/extract_chrome_session.js
 */

import sqlite3 from 'sqlite3';
import { open } from 'sqlite';
import { execSync } from 'child_process';
import crypto from 'crypto';
import path from 'path';
import fs from 'fs';
import os from 'os';
import { fileURLToPath } from 'url';

const __dirname    = path.dirname(fileURLToPath(import.meta.url));
const SESSION_PATH = path.resolve(__dirname, '../config/linkedin_session.json');
const CONFIG_DIR   = path.dirname(SESSION_PATH);
const HOME         = os.homedir();

// Base directories for Chrome variants on macOS
const CHROME_BASES = [
    path.join(HOME, 'Library/Application Support/Google/Chrome'),
    path.join(HOME, 'Library/Application Support/Chromium'),
    path.join(HOME, 'Library/Application Support/BraveSoftware/Brave-Browser'),
];

/**
 * Find the Chrome Cookies database that has the most recently-expiring li_at
 * token (i.e. the active LinkedIn session), scanning all profiles.
 */
async function findBestCookieDb() {
    let best = null;  // { path, expires }

    for (const base of CHROME_BASES) {
        if (!fs.existsSync(base)) continue;
        let profiles;
        try { profiles = fs.readdirSync(base); } catch { continue; }

        for (const profile of profiles) {
            const dbPath = path.join(base, profile, 'Cookies');
            if (!fs.existsSync(dbPath)) continue;
            const tmp = path.join(os.tmpdir(), `probe_${profile}_${Date.now()}.db`);
            try {
                fs.copyFileSync(dbPath, tmp);
                const db = await open({ filename: tmp, driver: sqlite3.Database });
                const row = await db.get(
                    `SELECT expires_utc FROM cookies WHERE name = 'li_at' AND host_key LIKE '%linkedin.com%' LIMIT 1`
                );
                await db.close();
                if (row?.expires_utc) {
                    const unix = Number((BigInt(row.expires_utc) - BigInt('11644473600000000')) / BigInt(1_000_000));
                    if (!best || unix > best.expires) {
                        best = { path: dbPath, expires: unix };
                    }
                }
            } catch { /* skip unreadable profiles */ } finally {
                if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
            }
        }
    }

    if (!best) {
        throw new Error(
            'Could not find a Chrome profile with a LinkedIn session.\n' +
            'Please log into LinkedIn in Chrome and try again.'
        );
    }
    return best.path;
}

// Get the Chrome Safe Storage encryption key from macOS Keychain
function getEncryptionKey() {
    for (const service of ['Chrome Safe Storage', 'Chromium Safe Storage', 'Brave Safe Storage']) {
        try {
            const raw = execSync(
                `security find-generic-password -w -s "${service}"`,
                { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
            ).trim();
            if (raw) {
                // Derive AES-128 key via PBKDF2-SHA1 (Chrome v10 scheme)
                return crypto.pbkdf2Sync(raw, 'saltysalt', 1003, 16, 'sha1');
            }
        } catch { /* try next */ }
    }
    throw new Error('Could not retrieve Chrome Safe Storage key from macOS Keychain.');
}

function decryptValue(encryptedBuf, key) {
    if (!encryptedBuf || encryptedBuf.length === 0) return '';
    const buf = Buffer.isBuffer(encryptedBuf) ? encryptedBuf : Buffer.from(encryptedBuf);
    const prefix = buf.slice(0, 3).toString('ascii');

    if (prefix === 'v10') {
        // AES-128-CBC, IV = 16 space bytes.
        // Chrome prepends a 16-byte random nonce to the plaintext before encrypting,
        // so after decryption the layout is: [16-byte nonce][cookie value][PKCS7 pad].
        // We strip the nonce; decipher.final() already strips the PKCS7 padding.
        const ciphertext = buf.slice(3);
        const iv = Buffer.alloc(16, ' ');
        try {
            const decipher  = crypto.createDecipheriv('aes-128-cbc', key, iv);
            const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
            // Chrome prepends a 32-byte prefix (2 blocks) before the plaintext value.
            // All blocks after the prefix decrypt correctly regardless of the IV.
            return decrypted.slice(32).toString('utf8');
        } catch {
            return '';
        }
    }

    if (prefix === 'v11') {
        // Chrome 127+: AES-128-GCM
        // Layout: [v11 (3)] [nonce (12)] [ciphertext (?)] [auth tag (16)]
        if (buf.length < 3 + 12 + 16) return ''; // too short to be valid
        const nonce      = buf.slice(3, 15);
        const authTag    = buf.slice(-16);
        const ciphertext = buf.slice(15, -16);
        try {
            const decipher  = crypto.createDecipheriv('aes-128-gcm', key, nonce);
            decipher.setAuthTag(authTag);
            const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
            // GCM plaintext may also have the 16-byte nonce prefix — strip if present
            return (decrypted.length > 16 ? decrypted.slice(16) : decrypted).toString('utf8');
        } catch {
            return '';
        }
    }

    // Unencrypted (older Chrome / dev builds)
    return buf.toString('utf8');
}

// Chrome epoch: microseconds since 1601-01-01 → Unix seconds
function chromeTimeToUnix(chromeMicros) {
    if (!chromeMicros || chromeMicros === 0) return -1;
    const OFFSET = BigInt('11644473600000000');
    return Number((BigInt(chromeMicros) - OFFSET) / BigInt(1_000_000));
}

const SAMESITE_MAP = { 0: 'None', 1: 'Lax', 2: 'Strict', '-1': 'None' };

async function main() {
    if (!fs.existsSync(CONFIG_DIR)) fs.mkdirSync(CONFIG_DIR, { recursive: true });

    const dbPath  = await findBestCookieDb();
    const tmpPath = path.join(os.tmpdir(), `chrome_cookies_${Date.now()}.db`);

    console.log(`🔍 Reading cookies from:\n   ${dbPath}`);

    // Copy the file first to avoid locking conflicts with running Chrome
    fs.copyFileSync(dbPath, tmpPath);

    // Also copy WAL/SHM if they exist (for consistent snapshot)
    for (const ext of ['-wal', '-shm']) {
        const src = dbPath + ext;
        if (fs.existsSync(src)) fs.copyFileSync(src, tmpPath + ext);
    }

    const db  = await open({ filename: tmpPath, driver: sqlite3.Database });
    const key = getEncryptionKey();

    const rows = await db.all(`
        SELECT name, value, encrypted_value, host_key, path, expires_utc,
               is_httponly, is_secure, samesite
        FROM cookies
        WHERE host_key LIKE '%linkedin.com%'
        ORDER BY host_key, name
    `);

    await db.close();

    // Clean up temp files
    for (const f of [tmpPath, tmpPath + '-wal', tmpPath + '-shm']) {
        if (fs.existsSync(f)) fs.unlinkSync(f);
    }

    if (rows.length === 0) {
        throw new Error('No LinkedIn cookies found — are you logged into LinkedIn in Chrome?');
    }

    const rawCookies = rows.map(row => {
        // Use plain `value` column if encrypted_value is absent/empty, otherwise decrypt
        row._plainValue = row.encrypted_value?.length
            ? decryptValue(row.encrypted_value, key)
            : (row.value || '');
        const secure   = row.is_secure === 1;
        let sameSite   = SAMESITE_MAP[String(row.samesite)] ?? 'None';
        // Playwright (and RFC 6265bis) require SameSite=None cookies to also be Secure
        if (sameSite === 'None' && !secure) sameSite = 'Lax';
        return {
            name:     row.name,
            value:    row._plainValue,
            domain:   row.host_key,
            path:     row.path,
            expires:  chromeTimeToUnix(row.expires_utc),
            httpOnly: row.is_httponly === 1,
            secure,
            sameSite,
        };
    });

    // Drop cookies that Playwright will reject:
    //  - empty name (shouldn't happen, but guard anyway)
    //  - names with characters invalid in HTTP headers
    const INVALID_NAME_RE = /[^\x21-\x7e]|[()<>@,;:\\"/[\]?={}]/;
    const cookies = rawCookies.filter(c => c.name && !INVALID_NAME_RE.test(c.name));

    const storageState = {
        cookies,
        origins: [{ origin: 'https://www.linkedin.com', localStorage: [] }],
    };

    fs.writeFileSync(SESSION_PATH, JSON.stringify(storageState, null, 2));

    const hasLiAt = cookies.some(c => c.name === 'li_at');
    console.log(`✅ Saved ${cookies.length} LinkedIn cookies → ${SESSION_PATH}`);
    console.log(`   Auth token (li_at): ${hasLiAt ? '✅ present' : '❌ missing — log into LinkedIn in Chrome first'}`);

    if (!hasLiAt) process.exit(1);
}

main().catch(err => {
    console.error('\n❌ Error:', err.message);
    process.exit(1);
});
