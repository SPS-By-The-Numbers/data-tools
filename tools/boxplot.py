from mizani.formatters import percent_format
from mizani.breaks import minor_breaks
from mizani.transforms import identity_trans

from plotnine import (
    ggplot,
    aes,
    geom_boxplot,
    geom_jitter,
    geom_point,
    geom_label,
    labs,
    position_jitter,
    scale_x_discrete,
    scale_y_continuous,
    theme_xkcd,
    theme_538,
    theme_grey,
    theme,
)

import pandas as pd

df = pd.read_csv('x-district-exp.csv')
df.sort_values('district', inplace=True)

raw_categories = [x for x in df['district']]
categories = list(dict.fromkeys(raw_categories))

# Create % variance
df['pct_variance'] = df['variance'] / df['budget']


class _trans(identity_trans):
    minor_breaks=staticmethod(minor_breaks(4))

x = (
    ggplot(df, aes(x="factor(district)",
                   y="pct_variance",
                   label="class_of",
                   color="district"

                   ))
    + geom_boxplot()
    + geom_label(position=position_jitter(0.25, 0, 1),
                 size="large",
                 angle=35)
    + scale_y_continuous(
        limits=[-.06,.12],
        labels=percent_format(),
        trans=_trans
    )
    + scale_x_discrete(labels=False)
    + labs(x="District",
           y="Variance as % of Budget",
           title="Expenditure Variance for Nearby Districts "
           )
    + theme_grey()
    + theme(legend_position='none')
)

print(df.head())


x.save('expenditures.svg', width=14, height=10.5)
