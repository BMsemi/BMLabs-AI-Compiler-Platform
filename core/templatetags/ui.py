from django import template
from django.utils.safestring import mark_safe
register = template.Library()

@register.simple_tag
def icon(name):
    paths = {
        'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
        'sidebar': '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18"/>',
        'close': '<path d="m6 6 12 12M6 18 18 6"/>',
        'spark': '<path d="m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7z"/>',
        'chevron': '<path d="m9 5 7 7-7 7"/>',
        'grid': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        'folder': '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11H3z"/>',
        'chip': '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',
        'code': '<path d="m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18"/>',
        'layers': '<path d="m12 3 10 5-10 5L2 8zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',
        'check': '<path d="m5 12 4 4L19 6"/><circle cx="12" cy="12" r="10"/>',
        'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        'users': '<circle cx="9" cy="8" r="3"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 4 5v2"/>',
        'book': '<path d="M12 5v16M2 3h5a5 5 0 0 1 5 2 5 5 0 0 1 5-2h5v16h-5a5 5 0 0 0-5 2 5 5 0 0 0-5-2H2z"/>',
        'settings': '<circle cx="12" cy="12" r="4"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/>',
        'arrow': '<path d="M4 12h16m-6-6 6 6-6 6"/>',
        'plus': '<path d="M12 5v14M5 12h14"/>',
        'file': '<path d="M14 2H4v20h16V8zm0 0v6h6M8 13h8m-8 4h6"/>',
        'terminal': '<path d="m4 6 6 6-6 6m9 0h7"/>',
        'lock': '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v3"/>',
        'search': '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
    }
    return mark_safe('<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths.get(name, paths['chip']) + '</svg>')
