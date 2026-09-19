/* The power-up glyphs as SVG path data on a 24 x 24 grid, drawn as vectors (never emoji). The same strings feed the
   canvas (Path2D) and the HUD chips (<path d>), so a pickup on the board and its chip in the corner always match. */
export const GLYPHS = Object.freeze({
  // a snowflake: three lines through the centre, each with a small fork at both ends
  freeze: 'M12 2.5v19M3.8 7.25l16.4 9.5M3.8 16.75l16.4-9.5M9.5 4.6L12 6.6l2.5-2M9.5 19.4l2.5-2 2.5 2M4.7 10.3l3.2.3-.7-3.1M19.3 13.7l-3.2-.3.7 3.1M4.7 13.7l3.2-.3-.7 3.1M19.3 10.3l-3.2.3.7-3.1',
  // a shield
  shield: 'M12 2.6l7.4 2.9v6.1c0 4.7-3.1 8.1-7.4 9.8-4.3-1.7-7.4-5.1-7.4-9.8V5.5z',
  // an hourglass
  slow: 'M6.5 3h11M6.5 21h11M7.5 3c0 4.2 3 5.6 4.5 9-1.5 3.4-4.5 4.8-4.5 9M16.5 3c0 4.2-3 5.6-4.5 9 1.5 3.4 4.5 4.8 4.5 9',
});

export const POWER_NAMES = Object.freeze({ freeze: 'Freeze', shield: 'Shield', slow: 'Slow' });
