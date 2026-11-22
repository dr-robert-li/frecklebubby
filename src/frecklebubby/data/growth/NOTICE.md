# WHO Child Growth Standards: LMS tables

This folder is NOT covered by the licence of the Frecklebubby code. The data belongs to the World Health Organization (WHO) and is used under WHO's own terms (below).

Retrieved: 2026-11-20

## Files

`weight_{F|M}.csv`, `length_{F|M}.csv`, `head_{F|M}.csv`: header `age_months,L,M,S`, one row per whole month 0..60. F = girls, M = boys. Weight in kg, length/height and head circumference in cm. Values are copied from the WHO "z-score" tables (columns Month, L, M, S) and rounded to 6 decimal places.

## Sources

- Weight-for-age: https://www.who.int/tools/child-growth-standards/standards/weight-for-age (files `wfa_boys_0-to-5-years_zscores.xlsx`, `wfa_girls_0-to-5-years_zscores.xlsx`)
- Length/height-for-age: https://www.who.int/tools/child-growth-standards/standards/length-height-for-age (files `lhfa_{boys,girls}_0-to-2-years_zscores.xlsx` for months 0-23 and `lhfa_{boys,girls}_2-to-5-years_zscores.xlsx` for months 24-60)
- Head circumference-for-age: https://www.who.int/tools/child-growth-standards/standards/head-circumference-for-age (files `hcfa-{boys,girls}-0-5-zscores.xlsx`)

The files are hosted on cdn.who.int and linked from those pages.

## Length versus height

WHO publishes length-for-age (recumbent, lying down) for 0-24 months and height-for-age (standing) from 24 months. The values were kept as published and not adjusted. Month 24 uses the standing-height table; the 0-2 years table's month-24 row (recumbent length) differs from it by about 0.7 cm and is not used. Callers should compare a measurement taken lying down against months below 24 and a standing measurement against 24 and above.

## Licence and reuse terms (as found on who.int, 2026-11-20)

WHO website terms of use (https://www.who.int/about/policies/terms-of-use):

> "Extracts of the information in the web site may be reviewed, reproduced or translated for research or private study but not for sale or for use in conjunction with commercial purposes. Any use of information in the web site should be accompanied by an acknowledgment of WHO as the source, citing the uniform resource locator (URL) of the article."

> "Reproduction or translation of substantial portions of the web site, or any use other than for educational or other non-commercial purposes, require explicit, prior authorization in writing."

WHO copyright and licensing page (https://www.who.int/about/policies/publishing/copyright):

> "The CC BY-NC-SA 3.0 IGO licence allows users to freely copy, reproduce, reprint, distribute, translate and adapt the work for non-commercial purposes, provided WHO is acknowledged as the source..."

> "The use of WHO materials that are not available under the CC BY-NC-SA 3.0 IGO licence is subject to permission being granted by WHO."

The growth standards pages themselves state no separate licence. Use of these tables is therefore non-commercial, with attribution to WHO. Anyone who redistributes this repository commercially should obtain written permission from WHO (permissions form linked from the copyright page). WHO does not endorse Frecklebubby.

Attribution: WHO Child Growth Standards, World Health Organization, 2006 (https://www.who.int/tools/child-growth-standards).
