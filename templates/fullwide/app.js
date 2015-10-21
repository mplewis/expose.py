var total = slides.length

function scrolledTo(pos) {
  var progress = document.getElementById('progress-inner')
  var width = pos * 100 / total + '%'
  console.log(width)
  progress.style.width = width
}

slides.forEach(function(id, i) {
  var elem = document.getElementById(id)
  if (!elem) return
  
  var watcher = scrollMonitor.create(elem)
  watcher.enterViewport(function() {
    scrolledTo(i + 1)
  })
})

scrolledTo(1)
