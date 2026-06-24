"""Program-matched ratios: pair each teacher group with the matching student population.
Teacher FTE is summed across duties 31-34 (special-ed teachers are ~92% duty 33, so per-duty
would be empty for the others — guide G10).  Output written to the repo root.
"""
import common as C


def main():
    cache = C.load()
    nonswd, swd = cache['nonswd'], cache['swd']
    fte_basic, fte_speced = cache['fte_basic'], cache['fte_speced']
    T = C.TEACHER_DUTIES

    def make(student, fte, title, sub, outfile):
        def val(y, sc):
            f = sum(fte.get((y, sc, d), 0.0) for d in T); s = student.get((y, sc))
            return s / f if (s and s > 0 and f >= C.MINFTE) else None
        C.facet_scatter(cache, val, title, sub, outfile, ylabel='students : teacher FTE')

    make(nonswd, fte_basic,
         'Seattle — non-SpecEd students : Basic-Education teacher FTE, by school & attendance area',
         'Non-special-ed students (all_students − students_with_disabilities) per Basic-Ed teacher FTE '
         '(programs: 1; duties 31-34 summed).',
         'seattle_ratio_basiced_teacher_nonsped.jpg')

    make(swd, fte_speced,
         'Seattle — SpecEd students : Special-Education teacher FTE (caseload), by school & attendance area',
         'Special-ed students (students_with_disabilities) per SpecEd teacher FTE '
         '(programs 21-29; duties 31-34 summed). A caseload of dedicated sped staff, not a class size.',
         'seattle_ratio_sped_teacher_sped.jpg')


if __name__ == '__main__':
    main()
