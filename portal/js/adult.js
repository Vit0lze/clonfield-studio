// «Ocultar adulto»: ON by default, one preference shared by the Library and the component search, one switch that is always easy to turn off.
const KEY = "cf-hide-adult";
const read = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
/** True unless the user turned it off on purpose. */
export const hideAdult = () => read() !== "0";
export function setHideAdult(value) { try { localStorage.setItem(KEY, value ? "1" : "0"); } catch { /* private mode */ } }
export const visible = item => !(hideAdult() && item.adult);
