export function normalizeUrl(url) {
    if (!url) return null;
    try {
        const u = new URL(url);
        // Remove tracking and session parameters
        const paramsToRemove = [
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'ref', 'refId', 'trackingId', 'trk', 'checkpoint', 'session_id', 'click_id'
        ];
        paramsToRemove.forEach(p => u.searchParams.delete(p));
        
        // Handle LinkedIn specific normalization
        if (u.hostname.includes('linkedin.com')) {
            // LinkedIn often appends a trackingId to the path or as a param
            // We've already handled params, but keep the path clean
            return u.origin + u.pathname; 
        }

        return u.toString();
    } catch (e) {
        return url; // Fallback to raw if URL parsing fails
    }
}
