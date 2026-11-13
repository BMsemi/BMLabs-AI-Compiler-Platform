(() => {
  const video = document.getElementById('walkthrough-video');
  const status = document.getElementById('walkthrough-status');
  const chapters = [...document.querySelectorAll('[data-time]')];
  async function play() {
    video.muted = false;
    video.volume = 1;
    try {
      await video.play();
      status.textContent = 'Playing with voice-over. Adjust the player or system volume as needed.';
    } catch (error) {
      status.textContent = 'Playback could not start. Press the video Play control, or use Download video to open it in your media player.';
    }
  }
  document.getElementById('walkthrough-play').addEventListener('click', play);
  chapters.forEach(button => button.addEventListener('click', () => {
    video.currentTime = Number(button.dataset.time);
    play();
  }));
  video.addEventListener('loadeddata', () => {
    if (video.paused) status.textContent = 'Video ready. Press Play with voice-over.';
  });
  video.addEventListener('error', () => {
    status.textContent = 'This browser could not load the video. Use Download video to watch it in your media player.';
  });
  video.addEventListener('timeupdate', () => {
    let active = chapters[0];
    for (const button of chapters) if (Number(button.dataset.time) <= video.currentTime) active = button;
    chapters.forEach(button => button.setAttribute('aria-current', button === active ? 'step' : 'false'));
  });
})();
