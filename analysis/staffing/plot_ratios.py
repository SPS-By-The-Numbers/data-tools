"""Per-duty student:FTE ratio graphs (one per duty title), plus Basic-Education-only versions
for the teacher duties.  Output: seattle_ratio_duty_<d>.jpg and seattle_ratio_basiced_<d>.jpg
(written to the repo root).  See guide G10-G12.
"""
import common as C


def dname(C_, d):
    return C_['duty_name'][d]


def main():
    cache = C.load()
    enr_all, fte_all, fte_basic = cache['enr_all'], cache['fte_all'], cache['fte_basic']

    def ratio(fte, y, sc, d):
        f = fte.get((y, sc, d), 0.0); e = enr_all.get((y, sc))
        return e / f if (e and f >= C.MINFTE) else None

    nm = cache['duty_name']

    # request: one graph per duty title (all programs)
    for d in C.RATIO_DUTIES:
        C.facet_scatter(
            cache, (lambda y, sc, d=d: ratio(fte_all, y, sc, d)),
            f'Seattle — student : {nm[d]} ({d}) FTE ratio by school, by attendance area',
            f'Students per {nm[d]} FTE.',
            f'seattle_ratio_duty_{d}.jpg', types=C.LEVEL.get(d))

    # Basic Education program only, teacher duties
    for d in C.TEACHER_DUTIES:
        C.facet_scatter(
            cache, (lambda y, sc, d=d: ratio(fte_basic, y, sc, d)),
            f'Seattle — student : {nm[d]} ({d}) ratio — BASIC EDUCATION program only',
            f'Students per {nm[d]} FTE, counting Basic-Education program FTE only (program 1).',
            f'seattle_ratio_basiced_{d}.jpg', types=C.LEVEL.get(d))


if __name__ == '__main__':
    main()
