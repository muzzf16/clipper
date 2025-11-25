// 🎬 Clippy - Process Page JavaScript

class ProcessPage {
    constructor() {
        this.jobId = document.getElementById('job-id').value;
        this.socket = null;
        this.progressCircle = document.getElementById('progress-circle');
        this.progressPercentage = document.getElementById('progress-percentage');
        this.progressMessage = document.getElementById('progress-message');

        if (!this.jobId) {
            window.location.href = '/';
            return;
        }

        this.initializeSocket();
        this.checkJobStatus();
    }

    initializeSocket() {
        // Connect with job_id as query parameter
        this.socket = io({
            query: {
                job_id: this.jobId
            }
        });

        // Socket event listeners
        this.socket.on('connect', () => {
            console.log('Connected to server');
        });

        this.socket.on('connected', (data) => {
            console.log('Joined room:', data.room);
        });

        this.socket.on('progress_update', (data) => {
            if (data.job_id === this.jobId) {
                this.updateProgress(data);
            }
        });

        this.socket.on('clip_completed', (data) => {
            if (data.job_id === this.jobId) {
                this.handleClipCompleted(data);
            }
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
        });
    }

    async checkJobStatus() {
        console.log('Checking job status for:', this.jobId);
        try {
            const response = await fetch(`/api/job_status/${this.jobId}`);
            if (!response.ok) {
                console.error('Job status response not OK:', response.status);
                throw new Error('Job not found');
            }

            const job = await response.json();
            console.log('Job status:', job);

            if (job.status === 'completed') {
                // Job already completed, redirect to edit
                console.log('Job completed, redirecting to edit page');
                window.location.href = `/edit?job_id=${this.jobId}`;
            } else if (job.status === 'error') {
                console.error('Job error:', job.error);
                this.showError(job.error || 'Processing failed');
            } else {
                // Update UI with current progress
                console.log('Updating progress:', job.progress);
                this.updateProgress({
                    progress: job.progress || 0,
                    message: job.message || 'Processing...'
                });
            }
        } catch (error) {
            console.error('Job status check error:', error);
            this.showError('Failed to load job status');
        }
    }

    updateProgress(data) {
        // Update circular progress
        const circumference = 2 * Math.PI * 90; // radius = 90
        const offset = circumference - (data.progress / 100) * circumference;
        this.progressCircle.style.strokeDashoffset = offset;

        // Update text
        this.progressPercentage.textContent = `${data.progress}%`;
        this.progressMessage.textContent = data.message;

        // Update steps
        this.updateProgressSteps(data.progress, data.message);

        // Handle error state
        if (data.status === 'error') {
            this.showError(data.message);
        }
    }

    updateProgressSteps(progress, message) {
        const steps = {
            'download': document.getElementById('step-download'),
            'analyze': document.getElementById('step-analyze'),
            'speakers': document.getElementById('step-speakers'),
            'captions': document.getElementById('step-captions'),
            'video': document.getElementById('step-video')
        };

        // Reset all steps
        Object.values(steps).forEach(step => {
            if (step) {
                step.classList.remove('active', 'completed');
            }
        });

        // Activate steps based on progress
        if (progress >= 10) {
            steps.download?.classList.add('active');
        }
        if (progress >= 30) {
            steps.download?.classList.remove('active');
            steps.download?.classList.add('completed');
            steps.analyze?.classList.add('active');
        }
        if (progress >= 50) {
            steps.analyze?.classList.remove('active');
            steps.analyze?.classList.add('completed');
            steps.speakers?.classList.add('active');
        }
        if (progress >= 70) {
            steps.speakers?.classList.remove('active');
            steps.speakers?.classList.add('completed');
            steps.captions?.classList.add('active');
        }
        if (progress >= 90) {
            steps.captions?.classList.remove('active');
            steps.captions?.classList.add('completed');
            steps.video?.classList.add('active');
        }
        if (progress >= 100) {
            steps.video?.classList.remove('active');
            steps.video?.classList.add('completed');
        }
    }

    handleClipCompleted(data) {
        // Show completion state briefly
        this.updateProgress({
            progress: 100,
            message: 'Clip generated successfully!'
        });

        // Redirect to edit page after a short delay
        setTimeout(() => {
            window.location.href = `/edit?job_id=${this.jobId}`;
        }, 1500);
    }

    showError(message) {
        console.error('ProcessPage Error:', message);

        // Get elements
        const progressContainer = document.querySelector('.progress-container');
        const errorState = document.getElementById('error-state');
        const errorDetails = document.getElementById('error-details');

        // Hide progress elements
        if (progressContainer) {
            progressContainer.style.display = 'none';
        }

        // Show error state
        if (errorState && errorDetails) {
            errorDetails.textContent = message;
            errorState.classList.remove('hidden');
            errorState.style.display = 'block'; // Ensure it's visible
            console.log('Error state displayed:', message);
        } else {
            console.error('Error state elements not found!');
            // Fallback: show alert if error elements missing
            alert('Error: ' + message);
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.processPage = new ProcessPage();
});
