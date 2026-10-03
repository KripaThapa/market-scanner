// A price-coordinate primitive: fill only between existing EMA values.
export default class EmaCloud {
  constructor(rows, first, second, color) {
    this.rows = rows;
    this.first = first;
    this.second = second;
    this.color = color;
    this.views = [{ zOrder: () => "bottom", renderer: () => this }];
  }
  attached({ chart, series }) {
    this.chart = chart;
    this.series = series;
  }
  paneViews() {
    return this.views;
  }
  draw(target) {
    target.useMediaCoordinateSpace(({ context }) => {
      context.fillStyle = this.color;
      for (let i = 1; i < this.rows.length; i++) {
        const a = this.rows[i - 1],
          b = this.rows[i];
        if (
          [a[this.first], a[this.second], b[this.first], b[this.second]].some(
            (v) => v == null,
          )
        )
          continue;
        const x1 = this.chart.timeScale().timeToCoordinate(a.time);
        const x2 = this.chart.timeScale().timeToCoordinate(b.time);
        const y = [
          a[this.first],
          b[this.first],
          b[this.second],
          a[this.second],
        ].map((v) => this.series.priceToCoordinate(v));
        if (x1 == null || x2 == null || y.some((v) => v == null)) continue;
        context.beginPath();
        context.moveTo(x1, y[0]);
        context.lineTo(x2, y[1]);
        context.lineTo(x2, y[2]);
        context.lineTo(x1, y[3]);
        context.closePath();
        context.fill();
      }
    });
  }
}
