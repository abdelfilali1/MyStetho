/**
 * Point d'entrée du module odontogramme / parodontogramme.
 *
 *   const m = await import('/static/js/odonto/index.js');
 *   m.mountOdontogram(el, { patientId, consultationId });
 *   m.mountPeriodontogram(el, { patientId });
 */

import { mountOdontogram } from './chart.js';
import { mountPeriodontogram } from './perio.js';

export { mountOdontogram, mountPeriodontogram };

window.Odonto = { mountOdontogram, mountPeriodontogram };
