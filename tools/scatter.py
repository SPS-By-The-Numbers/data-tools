from mizani.formatters import percent_format
from mizani.breaks import minor_breaks
from mizani.transforms import identity_trans
import sys

from plotnine import (
    ggplot,
    aes,
    geom_jitter,
    geom_point,
    geom_label,
    geom_rect,
    geom_smooth,
    labs,
    position_jitter,
    scale_x_discrete,
    scale_x_continuous,
    scale_y_continuous,
    scale_y_discrete,
    facet_wrap,
    theme_xkcd,
    theme_538,
    theme_grey,
    theme,
)

import pandas as pd

df = pd.read_csv('school-board-endorsements.csv')
df.sort_values('Year', inplace=True)
df = df[df['endorsement'].isin(['stranger', 'times'])]
df['vote_pct'] = df['% vote'].str.replace('%', '')
df['vote_pct'] = pd.to_numeric(df['vote_pct'])
df['vote_pct'] = df['vote_pct'] / 100

df['endorsement'] = df['endorsement'].replace(
    {'stranger': 'The Stranger',
     'times': 'The Seattle Times'})
pd.set_option('display.max_rows', None)
print(df)


graph = df[df['Times'] == 'x']

df_win_rect = pd.DataFrame({
    'xmin': [0.5],
    'xmax': [1],
    'ymin': [2003],
    'ymax': [2007]
})


x = (
    ggplot(graph, aes(y='Year', x="vote_pct"))
    #+ geom_jitter(width = 0)
    + geom_point()
    + geom_smooth(method='lm', color='red')
    + scale_y_continuous(
        limits=[2003,2027],
        breaks=range(2003, 2027, 2)
    )
    + scale_x_continuous(
        limits=[0,1],
        labels=percent_format(),
    )
    + theme_grey()
    + theme(legend_position='none')
    + labs(x="% of Vote",
           y="Year",
           title="Seattle Times Endorsement % of Vote Over The Years"
           )
)


x.save('times.svg', width=6, height=4)
