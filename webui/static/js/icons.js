/**
 * Icon library — static/js/icons.js
 *
 * Inline SVGs hand-built to match iconsax.io's "Linear" style (24x24
 * viewBox, 1.5px rounded stroke, no fill) since this is a static HTML/JS
 * app with no bundler to pull the iconsax-react package through, and no
 * reachable CDN for the raw SVG set from this sandbox. Kept in one place
 * so every icon shares the same stroke-width/currentColor convention.
 */
const ICONS = {
  home: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 21V16C9 15.4477 9.44772 15 10 15H14C14.5523 15 15 15.4477 15 16V21" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 12.5L10.6 4.9C11.4 4.2 12.6 4.2 13.4 4.9L22 12.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 10.5V19C4 20.1046 4.89543 21 6 21H18C19.1046 21 20 20.1046 20 19V10.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  rocket: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C14 4 16.5 7.5 16.5 11.5C16.5 14.5 15 17 12 20C9 17 7.5 14.5 7.5 11.5C7.5 7.5 10 4 12 2Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="10.5" r="1.75" stroke="currentColor" stroke-width="1.5"/><path d="M8 16L5.5 18.5V21L8 19.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M16 16L18.5 18.5V21L16 19.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  plug: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 3V6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M15 3V6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M6 9H18V11C18 14.3137 15.3137 17 12 17C8.68629 17 6 14.3137 6 11V9Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 17V21" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M9 21H15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  setting: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M19.4 13.5C19.6 12.9 19.6 11.1 19.4 10.5L21 9.1L19.5 6.5L17.5 7.2C16.9 6.7 16.2 6.3 15.5 6L15 4H12H9L8.5 6C7.8 6.3 7.1 6.7 6.5 7.2L4.5 6.5L3 9.1L4.6 10.5C4.4 11.1 4.4 12.9 4.6 13.5L3 14.9L4.5 17.5L6.5 16.8C7.1 17.3 7.8 17.7 8.5 18L9 20H15L15.5 18C16.2 17.7 16.9 17.3 17.5 16.8L19.5 17.5L21 14.9L19.4 13.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,

  search: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M21 21L16.5 16.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  add: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 5V19" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M5 12H19" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  close: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M18 6L6 18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M6 6L18 18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  logout: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 8V6C9 4.89543 9.89543 4 11 4H17C18.1046 4 19 4.89543 19 6V18C19 19.1046 18.1046 20 17 20H11C9.89543 20 9 19.1046 9 18V16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M14 12H4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M7 9L4 12L7 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  check_circle: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/><path d="M8.5 12.5L10.8 14.8L15.5 9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  close_circle: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/><path d="M9.5 9.5L14.5 14.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M14.5 9.5L9.5 14.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  clock: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/><path d="M12 7.5V12L15 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  refresh: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4 12C4 7.58172 7.58172 4 12 4C15.0645 4 17.7315 5.72276 19.0899 8.26074" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M20 12C20 16.4183 16.4183 20 12 20C8.93552 20 6.26847 18.2772 4.91016 15.7393" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M19 4V8.5H14.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 20V15.5H9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  chart: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4 20V10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M10 20V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M16 20V13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M2 20H22" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  trash: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4 7H20" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M9 7V4H15V7" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M6 7L7 20H17L18 7" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,

  warning: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10.5 3.5L2.5 18C2 18.9 2.6 20 3.6 20H20.4C21.4 20 22 18.9 21.5 18L13.5 3.5C13 2.6 11 2.6 10.5 3.5Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 9.5V13.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="12" cy="16.5" r="0.9" fill="currentColor"/></svg>`,

  user: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="8" r="3.5" stroke="currentColor" stroke-width="1.5"/><path d="M4.5 20C5.3 16.5 8.3 14.5 12 14.5C15.7 14.5 18.7 16.5 19.5 20" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,

  lock: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="5" y="11" width="14" height="9" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M8 11V7.5C8 5.29086 9.79086 3.5 12 3.5C14.2091 3.5 16 5.29086 16 7.5V11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
};

function icon(name, cls = "icon") {
  const svg = ICONS[name] || "";
  return `<span class="${cls}">${svg}</span>`;
}
