import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const CACHE_PATH = join(__dirname, '../data/geo_cache.json');
const WESTWOOD_COORDS = { lat: 34.0633, lon: -118.4441 };
const MAX_DISTANCE_MILES = 15;

// Local Fallback for common LA areas to reduce API calls and handle "Access Denied"
const LOCAL_GEO = {
    "los angeles, ca": { lat: 34.0522, lon: -118.2437 },
    "los angeles metropolitan area, ca": { lat: 34.0522, lon: -118.2437 },
    "santa monica, ca": { lat: 34.0195, lon: -118.4912 },
    "culver city, ca": { lat: 34.0211, lon: -118.3965 },
    "beverly hills, ca": { lat: 34.0736, lon: -118.4004 },
    "century city, ca": { lat: 34.0581, lon: -118.4163 },
    "westwood, ca": { lat: 34.0633, lon: -118.4441 },
    "marina del rey, ca": { lat: 33.9803, lon: -118.4517 },
    "hawthorne, ca": { lat: 33.9164, lon: -118.3526 },
    "torrance, ca": { lat: 33.8358, lon: -118.3406 },
    "irvine, ca": { lat: 33.6846, lon: -117.8265 },
    "long beach, ca": { lat: 33.7701, lon: -118.1937 },
    "el segundo, ca": { lat: 33.9192, lon: -118.4165 },
    "chatsworth, ca": { lat: 34.2506, lon: -118.5976 },
    "glendale, ca": { lat: 34.1425, lon: -118.2551 },
    "pasadena, ca": { lat: 34.1478, lon: -118.1445 },
    "burbank, ca": { lat: 34.1808, lon: -118.3090 },
    "hollywood, ca": { lat: 34.0928, lon: -118.3287 },
    "venice, ca": { lat: 33.9850, lon: -118.4695 },
    "playa vista, ca": { lat: 33.9723, lon: -118.4239 },
    "manhattan beach, ca": { lat: 33.8847, lon: -118.4109 },
    "redondo beach, ca": { lat: 33.8492, lon: -118.3884 },
    "cerritos, ca": { lat: 33.8583, lon: -118.0648 },
    "san francisco, ca": { lat: 37.7749, lon: -122.4194 },
    "sylmar, ca": { lat: 34.3058, lon: -118.4448 },
    "anaheim, ca": { lat: 33.8366, lon: -117.9143 },
    "pomona, ca": { lat: 34.0551, lon: -117.7500 }
};

// Nominatim Rate Limiting: 1 req/sec
let lastRequestTime = 0;
const MIN_INTERVAL = 1500; 

function loadCache() {
    if (fs.existsSync(CACHE_PATH)) {
        return JSON.parse(fs.readFileSync(CACHE_PATH, 'utf8'));
    }
    return {};
}

function saveCache(cache) {
    if (!fs.existsSync(dirname(CACHE_PATH))) {
        fs.mkdirSync(dirname(CACHE_PATH), { recursive: true });
    }
    fs.writeFileSync(CACHE_PATH, JSON.stringify(cache, null, 2));
}

export function haversineDistance(coords1, coords2) {
    const R = 3958.8; // Radius of Earth in miles
    const dLat = (coords2.lat - coords1.lat) * Math.PI / 180;
    const dLon = (coords2.lon - coords1.lon) * Math.PI / 180;
    const a = 
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(coords1.lat * Math.PI / 180) * Math.cos(coords2.lat * Math.PI / 180) * 
        Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

export async function getCoords(locationStr) {
    if (!locationStr) return null;
    
    // Normalize string: lower case, remove text in parentheses
    let city = locationStr.toLowerCase().split('(')[0].trim();
    if (!city.includes(',') && !city.includes('remote')) city += ', ca';

    // Check Local Fallback
    if (LOCAL_GEO[city]) return LOCAL_GEO[city];

    const cache = loadCache();
    if (cache[city]) return cache[city];

    // Rate Limit
    const now = Date.now();
    if (now - lastRequestTime < MIN_INTERVAL) {
        await new Promise(resolve => setTimeout(resolve, MIN_INTERVAL - (now - lastRequestTime)));
    }
    lastRequestTime = Date.now();

    console.log(`   🔍 Geocoding via API: ${city}`);
    const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(city)}&format=json&limit=1`;
    
    try {
        const response = await fetch(url, {
            headers: {
                'User-Agent': 'GeminiJobHunterProject/1.0 (https://github.com/lukeren; lukeren@example.com)' 
            }
        });

        if (!response.ok) {
            console.error(`      ❌ API Error: ${response.status} ${response.statusText}`);
            return null;
        }

        const data = await response.json();
        
        if (data && data.length > 0) {
            const coords = { lat: parseFloat(data[0].lat), lon: parseFloat(data[0].lon) };
            cache[city] = coords;
            saveCache(cache);
            return coords;
        }
    } catch (err) {
        console.error(`      ❌ Geocoding failed for ${city}:`, err.message);
    }
    return null;
}

export async function isWithinRange(locationStr) {
    if (!locationStr || locationStr.toLowerCase().includes('remote')) return true;

    const coords = await getCoords(locationStr);
    if (!coords) {
        console.log(`   ⚠️ Could not determine distance for: ${locationStr}. Skipping to be safe.`);
        return false;
    }

    const distance = haversineDistance(WESTWOOD_COORDS, coords);
    const inRange = distance <= MAX_DISTANCE_MILES;
    console.log(`   📍 Distance to ${locationStr}: ${distance.toFixed(2)} miles | In Range: ${inRange}`);
    return inRange;
}
