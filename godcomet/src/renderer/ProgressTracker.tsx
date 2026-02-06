import React, { useEffect, useState } from 'react';

interface WorkflowStep {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration?: number;
  message?: string;
}

interface WorkflowProgress {
  workflow_id: string;
  state: string;
  step: string;
  progress: number;
  elapsed_time: number;
  message?: string;
}

interface ProgressTrackerProps {
  workflowId?: string;
  onComplete?: (result: any) => void;
  onError?: (error: any) => void;
}

const defaultSteps: WorkflowStep[] = [
  { name: 'Extracting Figma design', status: 'pending' },
  { name: 'Generating React code', status: 'pending' },
  { name: 'Starting dev server', status: 'pending' },
  { name: 'Rendering website', status: 'pending' },
  { name: 'Visual audit', status: 'pending' },
  { name: 'Awaiting approval', status: 'pending' },
  { name: 'Creating GitHub repo', status: 'pending' },
  { name: 'Deploying to Vercel', status: 'pending' },
];

export const ProgressTracker: React.FC<ProgressTrackerProps> = ({
  workflowId,
  onComplete,
  onError
}) => {
  const [steps, setSteps] = useState<WorkflowStep[]>(defaultSteps);
  const [currentStep, setCurrentStep] = useState('');
  const [progress, setProgress] = useState(0);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [message, setMessage] = useState('');
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Listen for workflow progress updates
    const api = (window as any).api;

    if (api?.onWorkflowProgress) {
      api.onWorkflowProgress((data: { data: WorkflowProgress }) => {
        const progressData = data.data;

        if (workflowId && progressData.workflow_id !== workflowId) {
          return; // Ignore updates for other workflows
        }

        setIsVisible(true);
        setCurrentStep(progressData.step);
        setProgress(progressData.progress);
        setElapsedTime(progressData.elapsed_time);
        setMessage(progressData.message || '');

        // Update steps
        setSteps(prev => prev.map(step => {
          if (step.name === progressData.step) {
            return { ...step, status: 'running', message: progressData.message };
          }
          // Mark previous steps as completed
          const currentIndex = prev.findIndex(s => s.name === progressData.step);
          const stepIndex = prev.findIndex(s => s.name === step.name);
          if (stepIndex < currentIndex && step.status !== 'completed') {
            return { ...step, status: 'completed' };
          }
          return step;
        }));
      });
    }

    if (api?.onWorkflowComplete) {
      api.onWorkflowComplete((data: any) => {
        // Mark all steps as completed
        setSteps(prev => prev.map(step => ({ ...step, status: 'completed' })));
        setProgress(100);
        onComplete?.(data.result);
      });
    }

    if (api?.onWorkflowError) {
      api.onWorkflowError((data: any) => {
        // Mark current step as failed
        setSteps(prev => prev.map(step => {
          if (step.status === 'running') {
            return { ...step, status: 'failed', message: data.error?.message };
          }
          return step;
        }));
        onError?.(data.error);
      });
    }
  }, [workflowId, onComplete, onError]);

  if (!isVisible) {
    return null;
  }

  const formatTime = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
  };

  const getStepIcon = (status: string) => {
    switch (status) {
      case 'completed': return '✅';
      case 'running': return '⏳';
      case 'failed': return '❌';
      default: return '○';
    }
  };

  return (
    <div className="progress-tracker">
      <div className="progress-header">
        <span className="progress-title">Workflow Progress</span>
        <span className="progress-time">{formatTime(elapsedTime)}</span>
      </div>

      <div className="progress-bar-container">
        <div
          className="progress-bar"
          style={{ width: `${progress}%` }}
        />
        <span className="progress-percent">{progress}%</span>
      </div>

      <div className="progress-steps">
        {steps.map((step, index) => (
          <div
            key={index}
            className={`progress-step ${step.status}`}
          >
            <span className="step-icon">{getStepIcon(step.status)}</span>
            <span className="step-name">{step.name}</span>
            {step.status === 'running' && (
              <span className="step-spinner" />
            )}
          </div>
        ))}
      </div>

      {message && (
        <div className="progress-message">
          {message}
        </div>
      )}

      <style>{`
        .progress-tracker {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 12px;
          padding: 16px;
          margin: 16px 0;
        }

        .progress-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .progress-title {
          font-weight: 600;
          color: #fff;
        }

        .progress-time {
          font-size: 14px;
          color: #9ca3af;
        }

        .progress-bar-container {
          position: relative;
          height: 8px;
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
          overflow: hidden;
          margin-bottom: 16px;
        }

        .progress-bar {
          height: 100%;
          background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
          border-radius: 4px;
          transition: width 0.3s ease;
        }

        .progress-percent {
          position: absolute;
          right: -40px;
          top: -4px;
          font-size: 12px;
          color: #9ca3af;
        }

        .progress-steps {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .progress-step {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          color: #6b7280;
          padding: 4px 0;
        }

        .progress-step.completed {
          color: #10b981;
        }

        .progress-step.running {
          color: #667eea;
          font-weight: 500;
        }

        .progress-step.failed {
          color: #ef4444;
        }

        .step-icon {
          width: 20px;
          text-align: center;
        }

        .step-spinner {
          width: 12px;
          height: 12px;
          border: 2px solid rgba(102, 126, 234, 0.3);
          border-top-color: #667eea;
          border-radius: 50%;
          animation: spin 1s linear infinite;
          margin-left: auto;
        }

        .progress-message {
          margin-top: 12px;
          padding: 8px 12px;
          background: rgba(102, 126, 234, 0.1);
          border-radius: 6px;
          font-size: 13px;
          color: #a5b4fc;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default ProgressTracker;
